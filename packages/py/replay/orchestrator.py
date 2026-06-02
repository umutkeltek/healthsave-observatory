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
