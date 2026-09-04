"""POST ``/api/v2/apple/batch`` — versioned Apple HealthKit ingest.

Plan: 2026-09-03-v2-apple-ingest-wire.md, Slice 2.

The v1 ingest route ``POST /api/apple/batch`` is frozen (CLAUDE.md Law 5;
``IOS_CROSS_CHECK.md`` §"v1 contract" line 251). This is the additive v2
surface that accepts the new identity-aware keys Eric's longitudinal
engine needs:

  * ``samples[].uuid`` — HKSample.uuid survives delete-and-reinsert
    revisions on Apple's side, so a stable per-sample identity lets the
    v1 dedicated tables and the v2 canonical store distinguish revisions
    from duplicates. Migration 025 added ``source_uuid`` to
    heart_rate/hrv/blood_oxygen/body_temperature/sleep_sessions; the v2
    normalizer already reads ``source_record_uid`` for the canonical
    store (``packages/py/normalization/apple.py`` line 273).
  * ``samples[].startDate`` + ``samples[].endDate`` — interval window
    identity (Apple's RHR is interval-aggregated; the v1 wire only sent
    startDate, which made dawn-provisional vs afternoon-revision
    indistinguishable). v2 sends both. Falls back to legacy
    ``date``/``start`` for one release to ease the migration.
  * ``samples[].unit`` — explicit per-sample unit (UCUM/HKUnit.unitString).
    Server validates against the metric's allowed-units set; unknown
    unit is deterministic → 422 (frozen-client-safe; ``ingest.py`` line
    73–77).
  * ``samples[].tzOffsetMinutes`` — local UTC offset at the sample's
    startDate. Server stamps it on the raw payload and on the canonical
    row's provenance so downstream "local day" derivation is engine-side.
  * ``samples[].motionContext`` — heart-rate motion context
    (``HKMetadataKeyHeartRateMotionContext``: sedentary/active/notSet).
    Only meaningful on heart_rate today; ignored on other metrics.
  * Top-level ``deletions: [{uuid, deletedAt?}]`` — HKSample UUIDs that
    HealthKit reports as deleted. Applied atomically with the canonical
    write: ``canonical_observations.status='superseded'`` for matching
    ``source_record_uid`` AND v1 dedicated tables' ``status='superseded'``
    where ``source_uuid`` matches.

Wire rules:

  * ``schema_version`` is required and must equal 2; v1 clients get a
    422 (deterministic, never 500) so they don't wedge on the unknown
    schema.
  * The v1 route stays live for shipped clients; this route is additive
    in the URL layer and reuses the same idempotency/receipt machinery.

Pipeline (matches v1 ingest.py::apple_batch for compatibility):

  1. Validate v2 schema (Pydantic).
  2. Idempotency claim via ``_claim_or_replay_receipt_idempotency``.
  3. Audit log raw payload via ``audit.log_raw``.
  4. ``_write_canonical_observations`` — reuses v1 dual-write path.
  5. NEW: ``mark_canonical_observations_superseded`` (storage-zone helper
    added in this slice) — UPDATE on ``canonical_observations.status``.
  6. NEW: ``mark_v1_dedicated_superseded`` (storage-zone helper) — UPDATE
    on each of the five migrated dedicated tables where ``source_uuid``
    matches.
  7. ``plugin.ingest(...)`` with the canonical observations (projection
    layer keeps the v1 dedicated tables fresh from canonical writes).
  8. Receipt completion + ``RAW_LOG_ORPHANED`` error boundary.
  9. Return v1-equivalent delivery receipt.

NOT device-verifiable in this repo (CLAUDE.md Law 8 — this is server-only;
the iOS client change ships in Slice 3).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from compat_v1.models import BatchPayload  # noqa: F401  (used by sibling v1 tests)
from normalization import apple_wire_metric, normalize_apple_batch
from plugin_sdk import SDK_VERSION
from storage.defaults import observation_repository
from storage.timescale.measurements import (
    mark_canonical_observations_superseded,
    mark_v1_dedicated_superseded,
)
from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from ..ingestion.storage import (
    AuditLog,
    IngestStorage,
    default_audit_log,
    default_storage,
)
from .ingest import (
    APPLE_HEALTHKIT_SOURCE_ID,
    _APPLE_PLUGIN_ID,
    CANONICAL_DUAL_WRITE,
    CANONICAL_REJECTED,
    INGEST_BATCHES,
    INGEST_DURATION,
    INGEST_ROWS,
    RAW_LOG_ORPHANED,
    _claim_or_replay_receipt_idempotency,
    _delivery_receipt_response,
    _enrich_successful_sync_receipt,
    _header,
    _idempotency_key,
    _is_transient_write_error,
    _load_apple_health_plugin,
    _optional_int,
    _persist_orphaned_raw_payload,
    _rejection_reason_label,
    _record_failed_sync_receipt,
    _resolve_apple_health_plugin,
    _resolve_audit_log,
    _resolve_measurement_projection,
    _resolve_storage,
    _sample_window_from_request,
    _schedule_anomaly_check_if_enabled,
    _trusted_payload_hash,
    _write_canonical_observations,
)
from .deps import get_session, verify_api_key
from .swr import v2_read_cache

_log = logging.getLogger("healthsave.api.v2_apple_batch")

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])

_canonical_repo = observation_repository()

# SECURITY-004: bound batch size exactly like the v1 route. Over-limit is
# deterministic -> 422 so the iOS client (which retries 5xx forever) does not
# wedge the metric.
MAX_BATCH_SAMPLES = int(os.getenv("MAX_BATCH_SAMPLES", "50000"))


# ─────────────────────────────────────────────────────────────────────────
# Pydantic v2 request model
# ─────────────────────────────────────────────────────────────────────────


_MOTION_CONTEXT_VALUES = frozenset({"sedentary", "active", "notSet"})
_TZ_OFFSET_RANGE = range(-1440, 1441)  # inclusive
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class V2Sample(BaseModel):
    """Per-sample dict for the v2 wire — the transport envelope.

    Field-level validation here covers FORMAT only (UUID shape, ISO
    strings, tz/motion ranges) for whatever keys the sample carries.
    Which keys a sample MUST carry is a function of the batch's metric —
    HealthKit's seven emission families legitimately differ (anchored
    quantity samples carry uuid/startDate/endDate/unit; HKStatistics
    aggregates carry date+qty only; workouts, sleep, ECG and medication
    carry no qty/unit). Enforcing one family's shape on all of them
    422'd six of seven families deterministically — a Law-6 wedge for
    every frozen client. The metric-keyed semantic gate lives in
    ``V2AppleBatchPayload._sample_contract`` where the ontology answers
    which contract applies.

    Loose ``extra='allow'`` so future additive fields don't break
    shipped v2 clients (same forward-compat posture the v1 route has).
    """

    model_config = ConfigDict(extra="allow")

    uuid: str | None = Field(default=None, min_length=36, max_length=36)
    startDate: str | None = Field(default=None)
    endDate: str | None = Field(default=None)
    qty: float | int | None = Field(default=None)
    unit: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None)
    tzOffsetMinutes: int | None = Field(default=None)
    motionContext: str | None = Field(default=None)
    # Optional passthroughs used by sleep/workout/ECG — we don't enforce
    # shape here; the v1 parser already accepts them.
    start: str | None = Field(default=None)
    end: str | None = Field(default=None)
    duration: float | int | None = Field(default=None)
    value: str | int | float | None = Field(default=None)
    date: str | None = Field(default=None)
    endDate_iso: str | None = Field(default=None)

    @field_validator("uuid")
    @classmethod
    def _validate_uuid(cls, v: str | None) -> str | None:
        if v is not None and not _UUID_RE.match(v):
            raise ValueError("uuid must be a valid RFC4122 UUID string")
        return v

    @field_validator("startDate", "endDate", "start", "end", "date", mode="before")
    @classmethod
    def _require_iso(cls, v: Any) -> Any:
        # Lenient parser: accept any string the underlying normalize path can
        # handle; reject non-strings outright.
        if v is not None and (not isinstance(v, str) or not v.strip()):
            raise ValueError("must be a non-empty ISO-8601 string")
        return v

    @field_validator("unit")
    @classmethod
    def _validate_unit_shape(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("unit must be a non-empty string")
        return v

    @field_validator("source")
    @classmethod
    def _validate_source_shape(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("source must be a non-empty string")
        return v

    @field_validator("tzOffsetMinutes")
    @classmethod
    def _validate_tz(cls, v: int | None) -> int | None:
        if v is not None and v not in _TZ_OFFSET_RANGE:
            raise ValueError("tzOffsetMinutes must be between -1440 and +1440 inclusive")
        return v

    @field_validator("motionContext")
    @classmethod
    def _validate_motion(cls, v: str | None) -> str | None:
        if v is not None and v not in _MOTION_CONTEXT_VALUES:
            raise ValueError(
                "motionContext must be one of: sedentary, active, notSet"
            )
        return v


class V2Deletion(BaseModel):
    model_config = ConfigDict(extra="allow")

    uuid: str = Field(min_length=36, max_length=36)
    deletedAt: str | None = Field(default=None)

    @field_validator("uuid")
    @classmethod
    def _validate_uuid(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            raise ValueError("uuid must be a valid RFC4122 UUID string")
        return v

    @field_validator("deletedAt", mode="before")
    @classmethod
    def _validate_deleted_at(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, str) or not v.strip():
            raise ValueError("deletedAt must be a non-empty ISO-8601 string")
        return v


class V2AppleBatchPayload(BaseModel):
    """Wire model for ``POST /api/v2/apple/batch``.

    The schema is additive over v1: ``schema_version=2``, samples carry
    the identity-aware keys Eric's longitudinal engine needs
    (``uuid``/``startDate``/``endDate``/``unit``/``tzOffsetMinutes``/
    ``motionContext``), and a top-level ``deletions`` array propagates
    HealthKit's delete-and-reinsert revisions.

    ``model_config = ConfigDict(extra='allow')`` keeps the route
    forward-compatible for v2.x additive keys; unknown fields are ignored
    the same way v1 ignores unknown sample keys.

    Two-layer validation, deliberately split:

    * ``V2Sample`` field validators — FORMAT of whatever keys are
      present (UUID shape, non-empty strings, tz/motion domains).
    * ``_sample_contract`` below — WHICH keys must be present, decided
      per sample by its emission family and per metric by the ontology.
      HealthKit emits seven shapes (anchored quantity, statistics
      aggregates, workouts, sleep, ECG, medication, category events);
      pinning one family's key set on all of them 422'd six of seven
      families deterministically — a Law-6 wedge for frozen clients.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = Field(default=2)
    metric: str = Field(min_length=1, max_length=128)
    batch_index: int = Field(ge=0)
    total_batches: int = Field(ge=1)
    samples: list[V2Sample] = Field(default_factory=list)
    deletions: list[V2Deletion] = Field(default_factory=list)
    source_bundle_id: str | None = Field(default=None)
    device: dict[str, Any] | None = Field(default=None)

    @field_validator("schema_version")
    @classmethod
    def _v2_only(cls, v: int) -> int:
        # v1 clients that hit this route accidentally get a clean 422 — the
        # frozen-client-safe default from ingest.py::apple_batch line 73.
        if v != 2:
            raise ValueError(
                f"POST /api/v2/apple/batch requires schema_version=2; got {v}. "
                "Use POST /api/apple/batch for schema_version=1."
            )
        return v

    @model_validator(mode="after")
    def _sample_contract(self) -> "V2AppleBatchPayload":
        """Metric-keyed semantic gates the field layer cannot see.

        Identity gate (Eric's ask #6 — "sample uuid ... stable identity
        makes resync idempotent by construction"): any sample that
        declares an anchored shape (``startDate`` or ``start`` present)
        MUST carry its HKSample ``uuid`` — the supersede machinery
        (``mark_canonical_observations_superseded`` /
        ``mark_v1_dedicated_superseded``) and the
        ``(owner_id, source_uuid)`` partial unique index both key on it.
        Statistics aggregates carry ``date`` only and legitimately have
        no UUID, so the gate keys on the anchored-shape markers, not on
        the metric name — robust to new metrics and to aggregate
        deliveries of cumulative types.

        Interval gate (Eric's ask #1 — RHR window identity): an anchored
        sample must carry BOTH bounds; the end distinguishes a revision
        from a duplicate.

        Unit gate (Eric's ask #3 — "ours refuses unknown units"): when a
        sample declares ``unit`` and the metric resolves to an ontology
        quantity definition, the unit must be in that metric's
        ``allowed_units`` (HealthKit ``unitString`` spellings included).
        Unknown unit is deterministic → 422, never a silent guess.
        Samples without ``unit`` (HKStatistics aggregates) fall through
        to the normalizer's canonical-unit fallback — the statistics
        query unit equals the metric's canonical unit by construction
        (HealthTypes.swift reads every cumulative type in its canonical
        unit).
        """
        metric_def = apple_wire_metric(self.metric.strip())
        for idx, sample in enumerate(self.samples):
            anchored = sample.startDate is not None or sample.start is not None
            if anchored and sample.uuid is None:
                raise ValueError(
                    f"samples[{idx}].uuid missing: anchored samples "
                    "(startDate/start present) must carry the HKSample UUID "
                    "so delete-and-reinsert revisions stay supersedeable"
                )
            if sample.uuid is not None and not anchored:
                raise ValueError(
                    f"samples[{idx}].startDate missing: uuid-bearing samples "
                    "must carry startDate (or legacy start) — an identity "
                    "without an interval is unmatchable"
                )
            if anchored:
                has_bounds = (
                    sample.endDate is not None if sample.startDate is not None else sample.end is not None
                )
                if not has_bounds:
                    bound = "endDate" if sample.startDate is not None else "end"
                    raise ValueError(
                        f"samples[{idx}].{bound} missing: anchored samples "
                        "must carry both interval bounds (the end bound is "
                        "what distinguishes a revision from a duplicate)"
                    )
            if metric_def is not None and metric_def.allowed_units:
                # Eric's ask #3 — "a server that guesses a unit corrupts data
                # silently, so ours refuses instead". Anchored quantity
                # samples (startDate/start present, so qty is a measured
                # value in some unit) MUST declare their unit, and it must be
                # in the metric's ontology allowed_units (HealthKit
                # unitString spellings included via the 2026.09.0 ontology
                # revision). Unknown unit is deterministic → 422.
                #
                # Date-only HKStatistics aggregates are exempt: the
                # statistics query reads every cumulative type in the
                # metric's canonical unit by construction
                # (HealthTypes.swift), so the normalizer's canonical-unit
                # fallback is exact, and demanding the key would wedge the
                # committed wire which never sends it on aggregates.
                if anchored and sample.qty is not None and sample.unit is None:
                    raise ValueError(
                        f"samples[{idx}].unit missing: anchored quantity samples "
                        f"(qty present) for metric {self.metric!r} must declare "
                        f"their unit; allowed: {sorted(metric_def.allowed_units)}"
                    )
                if (
                    sample.unit is not None
                    and sample.unit not in metric_def.allowed_units
                ):
                    raise ValueError(
                        f"samples[{idx}].unit {sample.unit!r} is not allowed for "
                        f"metric {self.metric!r}; allowed: {sorted(metric_def.allowed_units)}"
                    )
        return self



# ──────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────


@router.post("/apple/batch")
async def v2_apple_batch(
    request: Request,
    background_tasks: BackgroundTasks = None,
    db_session: AsyncSession = Depends(get_session),
):
    """Receive a v2 Apple HealthKit batch.

    Wire contract: ``POST /api/v2/apple/batch`` with ``schema_version=2``.
    Accepts the same idempotency / receipt headers as v1 plus an optional
    ``X-HealthSave-Schema-Version: 2`` (advisory — the body schema_version
    is the source of truth).

    Response: same delivery-receipt shape as v1 with an additive
    ``wire_schema_version: 2`` and a ``deletions`` block carrying the
    per-table supersede counts.
    """
    started_at = datetime.now(UTC)
    raw_payload: dict[str, Any]
    try:
        raw_payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    payload_hash = await _trusted_payload_hash(request)
    try:
        parsed = V2AppleBatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        # Sanitize Pydantic's errors so the JSON response is always
        # serializable. Custom ``field_validator`` errors carry the
        # original ValueError instance in ``ctx.error``; ``include_url=False``
        # strips the docs URL (avoid leaking framework info to clients).
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc
    if len(parsed.samples) > MAX_BATCH_SAMPLES:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "error_code": "batch_too_large",
                "message": (
                    f"batch has {len(parsed.samples)} samples; max is "
                    f"{MAX_BATCH_SAMPLES} per request"
                ),
            },
        )

    try:
        owner_id = resolve_owner_id(request.headers.get(OWNER_HEADER))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {OWNER_HEADER}: {exc}") from exc

    storage = _resolve_storage(request)
    audit = _resolve_audit_log(request)
    projection = _resolve_measurement_projection(request)

    metric = parsed.metric.strip()
    batch_idx = parsed.batch_index
    total = parsed.total_batches
    # Convert Pydantic samples to plain dicts so downstream code (which is
    # already written for v1's free-form dict[]) doesn't need to learn
    # V2Sample. Extra keys on each sample pass through verbatim because we
    # use model_dump. ``exclude_none`` preserves the wire's absence
    # semantics: keys a family doesn't carry stay absent instead of
    # materializing as explicit ``null`` in the audit JSONB and in every
    # downstream ``sample.get(...)`` read.
    samples = [s.model_dump(exclude_none=True) for s in parsed.samples]
    deletion_uuids = [d.uuid for d in parsed.deletions]

    sample_min_at, sample_max_at = _sample_window_from_request(request, samples)
    sync_run_id = _header(request.headers, "X-HealthSave-Sync-Run-ID")
    batch_id = _header(request.headers, "X-HealthSave-Batch-ID")
    idempotency_key = _idempotency_key(
        request.headers,
        sync_run_id,
        batch_id,
        metric,
        batch_idx,
    )

    replayed_response = await _claim_or_replay_receipt_idempotency(
        db_session,
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        metric=metric,
        batch_index=batch_idx,
        total_batches=total,
    )
    if replayed_response is not None:
        await db_session.rollback()
        return replayed_response
    receipt_claimed = bool(idempotency_key and payload_hash)

    if not samples and not deletion_uuids:
        raw_log_id = await audit.log_raw(db_session, None, raw_payload) if audit else None
        response = _delivery_receipt_response(
            request=request,
            status="empty",
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            records_received=0,
            records_accepted=0,
            records_rejected=0,
            records_inserted_new=None,
            records_deduped_existing=None,
            storage_result_level="accepted_only",
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
        )
        response["wire_schema_version"] = 2
        if receipt_claimed:
            await complete_receipt_idempotency(
                db_session,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status="empty",
                response_payload=response,
                raw_log_id=raw_log_id,
                records_received=0,
                records_accepted=0,
                records_skipped=0,
                sample_min_at=sample_min_at,
                sample_max_at=sample_max_at,
            )
        if audit and raw_log_id is not None:
            await audit.mark_processed(db_session, raw_log_id)
        await db_session.commit()
        await _enrich_successful_sync_receipt(
            db_session,
            request=request,
            owner_id=owner_id,
            payload_hash=payload_hash,
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            status="empty",
            records_received=0,
            records_accepted=0,
            records_skipped=0,
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
            raw_log_id=raw_log_id,
            response_payload=response,
        )
        INGEST_BATCHES.labels(metric=metric, status="empty").inc()
        return response

    sample_groups = (
        # group_samples_by_device expects free-form dicts; reuse v1 helper.
        __import__(
            "server.ingestion.parsers",
            fromlist=["group_samples_by_device"],
        ).group_samples_by_device(samples)
    )
    first_device_name, _ = sample_groups[0] if sample_groups else ("HealthSave", [])

    raw_log_id = None
    canonical_deletion_count = 0
    v1_deletion_counts: dict[str, int] = {}

    try:
        first_device_id = await storage.get_or_create_device(db_session, first_device_name)
        raw_log_id = await audit.log_raw(db_session, first_device_id, raw_payload) if audit else None

        # Canonical writes first so the deletion pass can supersede rows
        # that the same batch just inserted (Apple's pattern: revise by
        # delete + add in the same anchor delivery).
        canonical_result = await _write_canonical_observations(
            db_session,
            metric=metric,
            samples=samples,
            owner_id=owner_id,
            raw_log_id=raw_log_id,
        )

        # Apply deletions atomically with the canonical write.
        if deletion_uuids:
            canonical_deletion_count = await mark_canonical_observations_superseded(
                db_session,
                owner_id=owner_id,
                uuids=deletion_uuids,
            )
            v1_deletion_counts = await mark_v1_dedicated_superseded(
                db_session,
                owner_id=owner_id,
                uuids=deletion_uuids,
            )

        # v1 projection layer keeps the legacy metric tables fresh from the
        # canonical writes. The plugin payload carries the v2 normalizer's
        # canonical observations for any downstream consumer that wants them.
        plugin = _resolve_apple_health_plugin(request)
        result = await plugin.ingest(
            {
                "storage": storage,
                "session": db_session,
                "device_id": first_device_id,
                "first_device_name": first_device_name,
                "projection": projection,
                "metric": metric,
                "samples": samples,
                "canonical_observations": canonical_result.observations,
                "owner_id": owner_id,
                "wire_schema_version": 2,
            }
        )
        count = int(result["accepted"])
        records_inserted_new = _optional_int(result.get("inserted_new"))
        records_deduped_existing = _optional_int(result.get("deduped_existing"))
        records_rejected = _optional_int(result.get("rejected")) or 0
        records_deduped_in_batch = _optional_int(result.get("deduped_in_batch"))
        storage_result_level = str(result.get("storage_result_level") or "accepted_only")
        response = _delivery_receipt_response(
            request=request,
            status="processed",
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            records_received=len(samples),
            records_accepted=count,
            records_rejected=records_rejected,
            records_inserted_new=records_inserted_new,
            records_deduped_existing=records_deduped_existing,
            storage_result_level=storage_result_level,
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
            records_deduped_in_batch=records_deduped_in_batch,
        )
        response["wire_schema_version"] = 2
        response["deletions"] = {
            "received": len(deletion_uuids),
            "canonical_superseded": canonical_deletion_count,
            "v1_dedicated_superseded": v1_deletion_counts,
        }
        if receipt_claimed:
            await complete_receipt_idempotency(
                db_session,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                status="processed",
                response_payload=response,
                raw_log_id=raw_log_id,
                records_received=len(samples),
                records_accepted=count,
                records_skipped=records_rejected,
                records_inserted_new=records_inserted_new,
                records_deduped_existing=records_deduped_existing,
                storage_result_level=storage_result_level,
                sample_min_at=sample_min_at,
                sample_max_at=sample_max_at,
            )
        if audit and raw_log_id is not None:
            await audit.mark_processed(db_session, raw_log_id)
        await db_session.commit()
        for key in ("canonical_coverage", "canonical_sources"):
            v2_read_cache.drop(key)
    except Exception as exc:
        try:
            RAW_LOG_ORPHANED.labels(metric=metric).inc()
        except Exception:  # pragma: no cover - metrics import optional
            _log.debug("failed to record RAW_LOG_ORPHANED{metric=%s}", metric)
        await db_session.rollback()
        orphaned_raw_log_id = await _persist_orphaned_raw_payload(
            db_session,
            audit=audit,
            storage=storage,
            first_device_name=first_device_name,
            raw_payload=raw_payload,
        )
        await _record_failed_sync_receipt(
            db_session,
            request=request,
            owner_id=owner_id,
            payload_hash=payload_hash,
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            records_received=len(samples),
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
            raw_log_id=orphaned_raw_log_id,
            error_message=str(exc),
        )
        _log.exception(
            "v2 ingest loop failed for %s; raw_log_id=%s left orphaned",
            metric,
            orphaned_raw_log_id,
        )
        if isinstance(exc, HTTPException):
            raise
        if _is_transient_write_error(exc):
            raise
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "error_code": "unprocessable_samples",
                "message": str(exc)[:500],
            },
        ) from exc

    # R2 Track A: registry enrichment runs after the atomic ingest commit.
    try:
        from normalization import identity as identity_mod
        from storage.timescale import registry

        await registry.record_origins(
            db_session,
            owner_id=owner_id,
            plugin_id=identity_mod.APPLE_HEALTHKIT_PLUGIN,
            origins=[name for name, _ in sample_groups],
        )
        await db_session.commit()
    except Exception:  # noqa: BLE001 - registry is best-effort
        _log.warning("v2 registry origin upsert failed (non-fatal)", exc_info=True)
        await db_session.rollback()

    await _enrich_successful_sync_receipt(
        db_session,
        request=request,
        owner_id=owner_id,
        payload_hash=payload_hash,
        metric=metric,
        batch_index=batch_idx,
        total_batches=total,
        status="processed",
        records_received=len(samples),
        records_accepted=count,
        records_skipped=records_rejected,
        records_inserted_new=records_inserted_new,
        records_deduped_existing=records_deduped_existing,
        storage_result_level=storage_result_level,
        sample_min_at=sample_min_at,
        sample_max_at=sample_max_at,
        raw_log_id=raw_log_id,
        response_payload=response,
    )

    canonical_accepted = int(getattr(canonical_result, "accepted", 0) or 0)
    if (canonical_accepted > 0) != (count > 0):
        _log.warning(
            "v2 dual-write divergence for %s: canonical_accepted=%d projection_accepted=%d",
            metric,
            canonical_accepted,
            count,
        )

    INGEST_DURATION.labels(metric=metric).observe(
        (datetime.now(UTC) - started_at).total_seconds()
    )
    INGEST_ROWS.labels(metric=metric).inc(count)
    INGEST_BATCHES.labels(metric=metric, status="processed").inc()
    _log.info(
        "v2 ingested %d records for %s (batch %d/%d); %d canonical deletions, %s",
        count,
        metric,
        batch_idx + 1,
        total,
        canonical_deletion_count,
        v1_deletion_counts,
    )
    _schedule_anomaly_check_if_enabled(request, background_tasks, count)
    return response