"""Replay orchestrator (ADR-0001 Decision H) — re-normalize stored raw payloads.

Reads raw source payloads back out of the audit log and runs them through the
*current* normalizer to (re)produce canonical observations. The canonical insert
is idempotent (``ON CONFLICT (owner, workspace, dedup_key, interval_start) DO
NOTHING``), so:

* a replay with an **unchanged** normalizer is a safe no-op, and
* a replay **after a mapping/ontology fix backfills** the observations that were
  previously dropped — e.g. the ``blood_oxygen`` rows unlocked by the wire alias
  added in this same foundation pass.

Scope (MVP): **additive backfill only.** Value-changing *supersede* — marking
prior observations ``status='superseded'`` when re-normalization yields a
*different* value for the same lineage — is deferred. It needs the raw→canonical
link made queryable first: today that link lives only in
``provenance.raw_payload_ref`` (a string), not the unused ``raw_payload_id``
column, and the canonical unique index is ``(owner, workspace, dedup_key,
interval_start)`` regardless of ``status``, so a superseded row blocks re-insert
of its replacement. See ``docs/FOUNDATION_READINESS.md``.

Pure + injectable: the raw reader and the canonical writer are passed in, so the
orchestration logic unit-tests against fakes with no database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, Provenance
from normalization import normalize_apple_batch

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from contracts.observation import Observation


class _CanonicalWriter(Protocol):
    """The slice of the canonical store the orchestrator needs (idempotent write)."""

    async def insert_many(self, session: Any, observations: list[Observation]) -> int: ...


@dataclass(frozen=True)
class ReplayReport:
    """Outcome of one replay run — honest, per-observation accounting."""

    run_id: str
    payloads_scanned: int
    observations_produced: int
    observations_rejected: int
    observations_submitted: int


async def replay_apple_raw_payloads(
    session: Any,
    *,
    raw_reader: Callable[..., Awaitable[list[tuple[int, dict]]]],
    repo: _CanonicalWriter,
    run_id: UUID,
    source_id: UUID,
    source_plugin_id: str = "apple_health",
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    after_id: int = 0,
    limit: int = 500,
) -> ReplayReport:
    """Re-normalize stored Apple raw payloads into canonical observations.

    Each produced observation is tagged with ``run_id`` (lineage) and submitted
    idempotently. ``raw_reader`` returns ``(raw_id, raw_payload)`` tuples; the
    ``raw_id`` is recorded in ``provenance.raw_payload_ref`` so a future replay
    (or a supersede pass) can trace back to the exact stored bytes.
    """
    raws = await raw_reader(session, after_id=after_id, limit=limit)
    produced = 0
    rejected = 0
    submitted = 0
    for raw_id, payload in raws:
        provenance = Provenance(
            source_plugin_id=source_plugin_id,
            sdk_version="replay",
            captured_at=datetime.now(UTC),
            raw_payload_ref=str(raw_id),
        )
        result = normalize_apple_batch(
            payload,
            source_id=source_id,
            provenance=provenance,
            owner_id=owner_id,
            workspace_id=workspace_id,
        )
        produced += result.accepted
        rejected += result.rejected
        if result.observations:
            tagged = [
                obs.model_copy(update={"normalization_run_id": run_id})
                for obs in result.observations
            ]
            submitted += await repo.insert_many(session, tagged)
    return ReplayReport(
        run_id=str(run_id),
        payloads_scanned=len(raws),
        observations_produced=produced,
        observations_rejected=rejected,
        observations_submitted=submitted,
    )


class _MetricSuperseder(Protocol):
    """Deletion replay scoped to one canonical metric (idempotent)."""

    async def __call__(
        self, session: Any, *, owner_id: UUID, metric_id: str, uuids: list[str]
    ) -> int: ...


@dataclass(frozen=True)
class MetricBackfillReport:
    """One page of a one-metric back-fill: what was read, written and skipped."""

    run_id: str
    metric_id: str
    payloads_scanned: int
    payloads_skipped_unknown_owner: int
    observations_produced: int
    observations_rejected: int
    observations_submitted: int
    deletions_applied: int
    last_raw_id: int


def _batch_for_normalizer(payload: dict) -> dict:
    """The ``{metric, samples}`` the live dual-write hands the normalizer.

    The v2 route validates each sample and passes ``model_dump(exclude_none=True)``;
    stored raw JSON may carry explicit nulls, so they are dropped the same way.
    """

    samples = payload.get("samples") or []
    if payload.get("schema_version") == 2:
        samples = [
            {k: v for k, v in sample.items() if v is not None}
            for sample in samples
            if isinstance(sample, dict)
        ]
    return {"metric": payload.get("metric"), "samples": samples}


def _deletion_uuids(payload: dict) -> list[str]:
    return [
        str(item["uuid"])
        for item in payload.get("deletions") or []
        if isinstance(item, dict) and item.get("uuid")
    ]


async def backfill_metric_from_raw(
    session: Any,
    *,
    raw_reader: Callable[..., Awaitable[list[tuple[int, dict, UUID | None]]]],
    repo: _CanonicalWriter,
    superseder: _MetricSuperseder,
    run_id: UUID,
    source_id: UUID,
    metric_id: str,
    fallback_owner_id: UUID | None,
    source_plugin_id: str = "apple_health",
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    after_id: int = 0,
    limit: int = 500,
) -> MetricBackfillReport:
    """Turn one metric's stored raw batches into canonical observations.

    For a metric the server stored raw but never mapped (RMSSD before
    ``vital.hrv_rmssd``). Additive and safe to run twice:

    * only observations of ``metric_id`` are written, through the same
      idempotent ``ON CONFLICT DO NOTHING`` insert the live dual-write uses,
      so a row already present (or already superseded) is never rewritten;
    * each batch's own deletions are replayed in stored order, scoped to
      ``metric_id``, so a sample HealthKit deleted later stays deleted and no
      other metric's row (SDNN) is ever touched;
    * the owner is the one the batch's sync receipt recorded; without one the
      batch goes to ``fallback_owner_id`` (a single-person Observatory) or is
      skipped and counted when that is ``None``.
    """

    raws = await raw_reader(session, after_id=after_id, limit=limit)
    produced = rejected = submitted = deleted = skipped = 0
    last_raw_id = after_id
    for raw_id, payload, receipt_owner in raws:
        last_raw_id = raw_id
        owner_id = receipt_owner or fallback_owner_id
        if owner_id is None:
            skipped += 1
            continue
        provenance = Provenance(
            source_plugin_id=source_plugin_id,
            sdk_version="replay",
            captured_at=datetime.now(UTC),
            raw_payload_ref=str(raw_id),
        )
        result = normalize_apple_batch(
            _batch_for_normalizer(payload),
            source_id=source_id,
            provenance=provenance,
            owner_id=owner_id,
            workspace_id=workspace_id,
        )
        keep = [
            obs.model_copy(update={"normalization_run_id": run_id})
            for obs in result.observations
            if obs.metric_id == metric_id
        ]
        produced += len(keep)
        rejected += result.rejected
        if keep:
            submitted += await repo.insert_many(session, keep)
        uuids = _deletion_uuids(payload)
        if uuids:
            deleted += await superseder(
                session, owner_id=owner_id, metric_id=metric_id, uuids=uuids
            )
    return MetricBackfillReport(
        run_id=str(run_id),
        metric_id=metric_id,
        payloads_scanned=len(raws),
        payloads_skipped_unknown_owner=skipped,
        observations_produced=produced,
        observations_rejected=rejected,
        observations_submitted=submitted,
        deletions_applied=deleted,
        last_raw_id=last_raw_id,
    )
