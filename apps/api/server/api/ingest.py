"""POST /api/apple/batch - receive a metric batch from a HealthSave client.

Phase 6.1: the per-device write loop delegates to the Apple Health
plugin via the Phase 6 plugin loader (``plugin_sdk.discover()`` →
``apple-health-healthsave`` → ``plugin.ingest(...)``). The plugin is
Protocol-aware: the route injects ``app.state.storage``
(``IngestStorage``) into the plugin payload so the Phase 5C backend-
swap seam keeps dispatching writes. The route still owns: payload
validation, owner-id resolution, raw audit log, the empty-batch
branch, the ``RAW_LOG_ORPHANED`` error boundary, the response shape,
and the post-ingest anomaly trigger.
"""

import json
import logging
import os
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from compat_v1.models import BatchPayload
from contracts._base import Provenance
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from normalization import normalize_apple_batch
from plugin_sdk import SDK_VERSION
from pydantic import ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import observation_repository
from storage.timescale.sync_receipts import (
    ReceiptIdempotencyConflict,
    _parse_time_value,
    assert_receipt_idempotency,
    record_sync_receipt,
)

from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from ..ingestion.parsers import group_samples_by_device
from ..ingestion.storage import (
    AuditLog,
    IngestStorage,
    default_audit_log,
    default_storage,
)
from .deps import get_session, verify_api_key
from .metrics import (
    CANONICAL_DUAL_WRITE,
    INGEST_BATCHES,
    INGEST_DURATION,
    INGEST_ROWS,
    RAW_LOG_ORPHANED,
    SYNC_RECEIPT_WRITE_FAILURES,
)

# v2 canonical write (Decision C). Stable source id for the Apple Health /
# HealthSave source; production adapter selection lives behind storage.defaults.
APPLE_HEALTHKIT_SOURCE_ID = UUID("a9b1e7e0-0000-4000-8000-000000000001")
_APPLE_PLUGIN_ID = "apple-health-healthsave"
# CONTRACT-001: classify ingest write failures by transient-vs-deterministic,
# NOT by an allow-list of deterministic types. The frozen iOS client retries any
# 5xx forever, so a deterministic 500 (e.g. a ProgrammingError from schema drift,
# or an ON CONFLICT key with no matching unique index, or a KeyError/TypeError in
# the write loop) head-of-line-blocks that metric's sync indefinitely. We
# therefore re-raise ONLY genuinely transient infra errors as 5xx; EVERY other
# failure is deterministic and returns 422, so the client retires the poison
# batch and recovers it via (idempotent) Backfill. Default-to-422 is the safe
# default here: a misclassified-transient 422 is recoverable via Backfill, while
# a misclassified-deterministic 500 wedges the metric forever.
_TRANSIENT_WRITE_ERRORS = (
    OperationalError,  # DB disconnect / deadlock / lock timeout / admin shutdown
    InterfaceError,  # connection-interface failure
    TimeoutError,  # builtin; asyncio.TimeoutError aliases this on 3.11+
    ConnectionError,  # builtin connection failures (reset/broken-pipe/refused)
)
_canonical_repo = observation_repository()

# SECURITY-004: bound the number of samples in a single batch so an unbounded
# array can't exhaust memory or hold a DB connection for an arbitrarily long
# write loop. Over-limit is deterministic -> 422 (frozen-client-safe: the client
# retires it and re-sends via the batch_index/total_batches chunking it already
# supports). 50k is far above any legitimate HealthKit batch.
MAX_BATCH_SAMPLES = int(os.getenv("MAX_BATCH_SAMPLES", "50000"))

if TYPE_CHECKING:
    from plugin_sdk import Source
    from storage.ports import MeasurementProjectionRepository

log = logging.getLogger("healthsave")

router = APIRouter()

# Phase 6.1: lazy module-level cache for the Apple Health plugin instance.
# Resolved on first request via ``_load_apple_health_plugin()`` and reused
# thereafter — discover/import are slow, idempotent, and not appropriate
# for the hot path. Lazy-at-first-request (NOT at module import) keeps the
# server.__init__ import cycle untouched: the plugin transitively imports
# from server.ingestion.parsers, which is fine at request time but would
# re-enter server.__init__ if it ran during route module load.
_apple_health_plugin: "Source | None" = None


def _load_apple_health_plugin() -> "Source":
    """Resolve and instantiate the Apple Health plugin via the SDK loader.

    Delegates to :func:`plugin_sdk.load_plugin` (Phase 7-pre-min) which
    runs ``discover()`` + ``assert_sdk_compatible`` + entrypoint import
    + base-class subclass check as one fail-loud chain. Caches the
    instance at the module level so subsequent calls are O(1).

    Surfaces:

      * :class:`PluginNotFoundError` — broken plugins/ layout.
      * :class:`PluginSdkVersionMismatch` — plugin targets an
        incompatible SDK. Phase 7-pre enforces this AT LOAD TIME, not
        later inside the runtime.
      * :class:`PluginEntrypointError` — import/attribute/subclass
        check failed.

    All three subclass :class:`PluginError` so a single
    ``except PluginError`` catches every load-side failure mode.
    """
    global _apple_health_plugin
    if _apple_health_plugin is not None:
        return _apple_health_plugin

    from plugin_sdk import load_plugin

    _apple_health_plugin = load_plugin("apple-health-healthsave", kind="source")
    log.info(
        "Apple Health plugin loaded via plugin_sdk: %s",
        _apple_health_plugin.manifest.entrypoint,
    )
    return _apple_health_plugin


def _resolve_apple_health_plugin(request: Request) -> "Source":
    """Read the configured plugin off ``app.state``, falling back to the
    module-level cache for unit tests that hit the route without a full
    FastAPI app + lifespan. Same pattern as ``_resolve_storage``.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    plugin = getattr(state, "apple_health_plugin", None)
    return plugin if plugin is not None else _load_apple_health_plugin()


@router.post("/api/apple/batch", dependencies=[Depends(verify_api_key)])
async def apple_batch(
    request: Request,
    session: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    """Receive a metric batch from HealthSave iOS app.

    Expected payload:
    {
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {"date": "2024-01-15T10:30:00Z", "qty": 72, "source": "Apple Watch"},
            ...
        ]
    }
    """
    started_at = perf_counter()
    try:
        raw_payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    try:
        payload = BatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if len(payload.samples) > MAX_BATCH_SAMPLES:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "error_code": "batch_too_large",
                "message": (
                    f"batch has {len(payload.samples)} samples; max is "
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

    metric = payload.metric.strip() or "unknown"
    batch_idx = payload.batch_index
    total = payload.total_batches
    samples = payload.samples
    sample_min_at, sample_max_at = _sample_window_from_request(request, samples)
    await _reject_conflicting_receipt_idempotency(
        session,
        request=request,
        metric=metric,
        batch_index=batch_idx,
    )

    if not samples:
        raw_log_id = await audit.log_raw(session, None, raw_payload) if audit else None
        await _record_sync_receipt(
            session,
            request=request,
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
        )
        await session.commit()
        if audit and raw_log_id is not None:
            await audit.mark_processed(session, raw_log_id)
            await session.commit()
        _observe_ingest_metrics(metric=metric, rows=0, started_at=started_at)
        return _delivery_receipt_response(
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

    sample_groups = group_samples_by_device(samples)
    first_device_name, _ = sample_groups[0]
    first_device_id = await storage.get_or_create_device(session, first_device_name)
    raw_log_id = await audit.log_raw(session, first_device_id, raw_payload) if audit else None
    await session.commit()

    plugin = _resolve_apple_health_plugin(request)

    # Phase 5G error boundary preserved: pre-5G the per-device loop ran
    # without exception handling; a mid-loop raise left
    # raw_ingestion_log.processed=false forever (raw_log_orphan; no
    # metric, no alert). Phase 6.1 wraps the plugin call in the same
    # try/except so the loader inherits the same observability
    # guarantee — operators alert on RAW_LOG_ORPHANED{metric}.
    try:
        # Canonical observations are the success gate; per-metric tables are a
        # downstream projection in the same transaction.
        canonical_result = await _write_canonical_observations(
            session, metric=metric, samples=samples, owner_id=owner_id, raw_log_id=raw_log_id
        )
        result = await plugin.ingest(
            {
                "storage": storage,
                "session": session,
                "device_id": first_device_id,
                "first_device_name": first_device_name,
                "projection": projection,
                "metric": metric,
                "samples": samples,
                "canonical_observations": canonical_result.observations,
                "owner_id": owner_id,
            }
        )
        count = int(result["accepted"])
        records_inserted_new = _optional_int(result.get("inserted_new"))
        records_deduped_existing = _optional_int(result.get("deduped_existing"))
        # Honest accounting: rejected = TRUE validation failures only (defaults
        # to 0 when a backend doesn't report it). Aggregation rollup (e.g. sleep
        # stages -> sessions) and in-batch dedupe are NOT rejections. Deriving
        # rejected as (received - accepted) reported ~95% of a healthy sleep
        # sync as rejected — see storage.results.IngestWriteResult.
        records_rejected = _optional_int(result.get("rejected")) or 0
        records_deduped_in_batch = _optional_int(result.get("deduped_in_batch"))
        storage_result_level = str(result.get("storage_result_level") or "accepted_only")
        if audit and raw_log_id is not None:
            await audit.mark_processed(session, raw_log_id)
        # CONTRACT-002: commit the DATA (canonical + projection + mark_processed)
        # here. The delivery receipt is written separately, best-effort, below —
        # a receipt-write failure must never roll back a landed ingest.
        await session.commit()
    except Exception as exc:
        try:
            RAW_LOG_ORPHANED.labels(metric=metric).inc()
        except Exception:  # pragma: no cover - metrics import optional
            log.debug("failed to record RAW_LOG_ORPHANED{metric=%s}", metric)
        await session.rollback()
        await _record_failed_sync_receipt(
            session,
            request=request,
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            records_received=len(samples),
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
            raw_log_id=raw_log_id,
            error_message=str(exc),
        )
        log.exception("ingest loop failed for %s; raw_log_id=%s left orphaned", metric, raw_log_id)
        # Already-classified HTTP errors pass through unchanged.
        if isinstance(exc, HTTPException):
            raise
        # Transient infra errors are retry-worthy → 5xx (client retries).
        if isinstance(exc, _TRANSIENT_WRITE_ERRORS):
            raise
        # Everything else is deterministic: a retry fails identically. Return 422
        # so the frozen client retires the batch instead of wedging on a 5xx.
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "error_code": "unprocessable_samples",
                "message": str(exc)[:500],
            },
        ) from exc

    # CONTRACT-002: the ingest above is durably committed. The delivery receipt is
    # bookkeeping for the /api/v2/sync surface — a receipt-write failure must NOT
    # roll back a good ingest or turn a landed batch into a 5xx/422 the client
    # would retry/Backfill. Best-effort, mirroring _record_failed_sync_receipt.
    try:
        await _record_sync_receipt(
            session,
            request=request,
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
        )
        await session.commit()
    except Exception:
        await session.rollback()
        log.exception(
            "sync receipt write failed AFTER a successful ingest for %s "
            "(data persisted; receipt row missing)",
            metric,
        )
        try:
            SYNC_RECEIPT_WRITE_FAILURES.labels(metric=metric).inc()
        except Exception:  # pragma: no cover - metrics import optional
            log.debug("failed to record SYNC_RECEIPT_WRITE_FAILURES{metric=%s}", metric)
    _observe_ingest_metrics(metric=metric, rows=count, started_at=started_at)
    log.info("Ingested %d records for %s (batch %d/%d)", count, metric, batch_idx + 1, total)
    _schedule_anomaly_check_if_enabled(request, background_tasks, count)

    return _delivery_receipt_response(
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


async def _write_canonical_observations(
    session: AsyncSession,
    *,
    metric: str,
    samples: list[dict[str, Any]],
    owner_id: Any,
    raw_log_id: int | None,
) -> Any:
    """Write v2 canonical observations inside the caller's ingest transaction."""
    provenance = Provenance(
        source_plugin_id=_APPLE_PLUGIN_ID,
        sdk_version=str(SDK_VERSION),
        captured_at=datetime.now(UTC),
        raw_payload_ref=str(raw_log_id) if raw_log_id is not None else None,
    )
    result = normalize_apple_batch(
        {"metric": metric, "samples": samples},
        source_id=APPLE_HEALTHKIT_SOURCE_ID,
        provenance=provenance,
        owner_id=owner_id,
    )
    if result.observations:
        await _canonical_repo.insert_many(session, result.observations)
    if result.accepted:
        CANONICAL_DUAL_WRITE.labels(metric=metric, result="ok").inc(result.accepted)
    if result.rejected:
        CANONICAL_DUAL_WRITE.labels(metric=metric, result="rejected").inc(result.rejected)
    return result


def _resolve_storage(request: Request) -> IngestStorage:
    """Read the configured storage backend off ``app.state``, falling back
    to the module-level default for unit tests that hit the route without
    a full FastAPI app + lifespan."""
    state = getattr(getattr(request, "app", None), "state", None)
    storage = getattr(state, "storage", None)
    return storage if storage is not None else default_storage


def _resolve_audit_log(request: Request) -> AuditLog | None:
    """Read the optional audit log backend off ``app.state``.

    Returns ``None`` when the configured backend doesn't ship one
    (InfluxDB-style append-only stores). The route skips audit calls
    in that case.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    if state is None:
        return default_audit_log
    # ``hasattr`` lets a backend explicitly disable audit by setting the
    # attribute to None on app.state, distinct from "not configured".
    if hasattr(state, "audit_log"):
        return state.audit_log
    return default_audit_log


def _resolve_measurement_projection(request: Request) -> "MeasurementProjectionRepository | None":
    """Read the canonical-to-v1 projection adapter from ``app.state``.

    Tests inject a recording double. Production falls back to the
    Timescale projection repository so canonical writes keep the
    Home Assistant/Grafana-facing metric tables fresh.
    """

    state = getattr(getattr(request, "app", None), "state", None)
    if state is not None:
        return getattr(state, "measurement_projection", None)

    from storage.timescale.measurements import default_projection_repository

    return default_projection_repository


def _header(headers: Any, name: str) -> str | None:
    """Read a request header from real Starlette Headers or test dicts."""

    value = headers.get(name)
    if value is not None:
        return str(value).strip() or None
    lower_name = name.lower()
    value = headers.get(lower_name)
    if value is not None:
        return str(value).strip() or None
    return None


def _header_int(headers: Any, name: str, fallback: int) -> int:
    value = _header(headers, name)
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _delivery_receipt_response(
    *,
    request: Request,
    status: str,
    metric: str,
    batch_index: int,
    total_batches: int,
    records_received: int,
    records_accepted: int,
    records_rejected: int,
    records_inserted_new: int | None,
    records_deduped_existing: int | None,
    storage_result_level: str,
    sample_min_at: str | None,
    sample_max_at: str | None,
    records_deduped_in_batch: int | None = None,
) -> dict[str, Any]:
    """Return legacy v1 fields plus an additive delivery receipt.

    The released app still reads the old ``status``/``records`` shape. The
    extra fields let newer clients separate transport delivery from later
    aggregate verification without changing the v1 ingest path.
    """

    headers = request.headers
    sync_run_id = _header(headers, "X-HealthSave-Sync-Run-ID")
    batch_id = _header(headers, "X-HealthSave-Batch-ID")
    idempotency_key = _idempotency_key(headers, sync_run_id, batch_id, metric, batch_index)
    receipt_id = idempotency_key or batch_id or f"{sync_run_id or 'runless'}:{metric}:{batch_index}"
    per_metric = {
        metric: {
            "received": records_received,
            "accepted": records_accepted,
            "rejected": records_rejected,
            "inserted_new": records_inserted_new,
            "deduped_existing": records_deduped_existing,
            "deduped_in_batch": records_deduped_in_batch,
            "sample_window": {
                "min_sample_time": sample_min_at,
                "max_sample_time": sample_max_at,
            },
        }
    }
    return {
        "status": status,
        "metric": metric,
        "batch": batch_index,
        "total_batches": total_batches,
        "records": records_accepted,
        "receipt_id": receipt_id,
        "sync_run_id": sync_run_id,
        "batch_id": batch_id,
        "idempotency_key": idempotency_key,
        "batch_index": batch_index,
        "records_received": records_received,
        "records_accepted": records_accepted,
        "records_rejected": records_rejected,
        "records_inserted_new": records_inserted_new,
        "records_deduped_existing": records_deduped_existing,
        "records_deduped_in_batch": records_deduped_in_batch,
        "storage_result_level": storage_result_level,
        "sample_window": {
            "min_sample_time": sample_min_at,
            "max_sample_time": sample_max_at,
        },
        "verification_level": "delivery_receipt",
        "per_metric": per_metric,
    }


async def _record_failed_sync_receipt(
    session: AsyncSession,
    *,
    request: Request,
    metric: str,
    batch_index: int,
    total_batches: int,
    records_received: int,
    sample_min_at: str | None,
    sample_max_at: str | None,
    raw_log_id: int | None,
    error_message: str,
) -> None:
    """Persist a failed receipt without changing the legacy failing response."""

    try:
        await _record_sync_receipt(
            session,
            request=request,
            metric=metric,
            batch_index=batch_index,
            total_batches=total_batches,
            status="failed",
            records_received=records_received,
            records_accepted=0,
            records_skipped=0,
            sample_min_at=sample_min_at,
            sample_max_at=sample_max_at,
            raw_log_id=raw_log_id,
            error_message=error_message[:1000],
        )
        await session.commit()
    except Exception:  # pragma: no cover - best-effort observability path
        await session.rollback()
        log.exception("failed to record HealthSave failed sync receipt for %s", metric)


async def _record_sync_receipt(
    session: AsyncSession,
    *,
    request: Request,
    metric: str,
    batch_index: int,
    total_batches: int,
    status: str,
    records_received: int,
    records_accepted: int,
    records_skipped: int,
    sample_min_at: str | None,
    sample_max_at: str | None,
    raw_log_id: int | None,
    records_inserted_new: int | None = None,
    records_deduped_existing: int | None = None,
    storage_result_level: str = "accepted_only",
    error_message: str | None = None,
) -> None:
    """Persist the HealthSave sync headers that released iOS already sends."""

    headers = request.headers
    sync_run_id = _header(headers, "X-HealthSave-Sync-Run-ID")
    batch_id = _header(headers, "X-HealthSave-Batch-ID")
    idempotency_key = _idempotency_key(headers, sync_run_id, batch_id, metric, batch_index)
    payload_hash = _header(headers, "X-HealthSave-Payload-Hash")
    header_metric = _header(headers, "X-HealthSave-Metric")

    await record_sync_receipt(
        session,
        sync_run_id=sync_run_id,
        batch_id=batch_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        metric=header_metric or metric,
        batch_index=_header_int(headers, "X-HealthSave-Batch-Index", batch_index),
        total_batches=_header_int(headers, "X-HealthSave-Total-Batches", total_batches),
        sync_mode=_header(headers, "X-HealthSave-Sync-Mode"),
        anchor_present=_header_bool(headers, "X-HealthSave-Anchor-Present"),
        lower_bound_reason=_header(headers, "X-HealthSave-Lower-Bound-Reason"),
        full_export=_header_bool(headers, "X-HealthSave-Full-Export"),
        query_lower_bound_at=_header(headers, "X-HealthSave-Query-Lower-Bound"),
        status=status,
        records_received=records_received,
        records_accepted=records_accepted,
        records_skipped=records_skipped,
        records_inserted_new=records_inserted_new,
        records_deduped_existing=records_deduped_existing,
        storage_result_level=storage_result_level,
        sample_min_at=sample_min_at,
        sample_max_at=sample_max_at,
        raw_log_id=raw_log_id,
        error_message=error_message,
    )


def _header_bool(headers: Any, name: str) -> bool | None:
    value = _header(headers, name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _idempotency_key(
    headers: Any,
    sync_run_id: str | None,
    batch_id: str | None,
    metric: str,
    batch_index: int,
) -> str | None:
    explicit_key = _header(headers, "Idempotency-Key")
    if explicit_key:
        return explicit_key
    if batch_id:
        return batch_id
    if sync_run_id:
        return f"{sync_run_id}:{metric}:{batch_index}"
    return None


async def _reject_conflicting_receipt_idempotency(
    session: AsyncSession,
    *,
    request: Request,
    metric: str,
    batch_index: int,
) -> None:
    headers = request.headers
    sync_run_id = _header(headers, "X-HealthSave-Sync-Run-ID")
    batch_id = _header(headers, "X-HealthSave-Batch-ID")
    idempotency_key = _idempotency_key(headers, sync_run_id, batch_id, metric, batch_index)
    payload_hash = _header(headers, "X-HealthSave-Payload-Hash")
    try:
        await assert_receipt_idempotency(
            session,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
    except ReceiptIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "rejected",
                "error_code": "idempotency_key_payload_mismatch",
                "message": str(exc),
            },
        ) from exc


def _sample_window_from_request(
    request: Request,
    samples: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    headers = request.headers
    header_min = _header(headers, "X-HealthSave-Sample-Min-Time")
    header_max = _header(headers, "X-HealthSave-Sample-Max-Time")
    if header_min or header_max:
        return _format_sample_window_time(header_min), _format_sample_window_time(header_max)
    return _sample_window_from_samples(samples)


def _sample_window_from_samples(samples: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    starts: list[tuple[datetime, str]] = []
    ends: list[tuple[datetime, str]] = []
    for sample in samples:
        for key in ("date", "startDate", "start_date", "start", "start_time", "time"):
            parsed = _parse_sample_time(sample.get(key))
            if parsed is not None:
                starts.append(parsed)
                break
        for key in ("endDate", "end_date", "end", "end_time", "date", "time"):
            parsed = _parse_sample_time(sample.get(key))
            if parsed is not None:
                ends.append(parsed)
                break
    min_sample = min(starts, default=None, key=lambda item: item[0])
    max_sample = max(ends, default=None, key=lambda item: item[0])
    return (
        min_sample[1] if min_sample is not None else None,
        max_sample[1] if max_sample is not None else None,
    )


def _parse_sample_time(value: Any) -> tuple[datetime, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text_value = value.strip()
    parse_value = text_value
    if parse_value.endswith("Z"):
        parse_value = f"{parse_value[:-1]}+00:00"
    try:
        return datetime.fromisoformat(parse_value), text_value
    except ValueError:
        return None


def _format_sample_window_time(value: str | None) -> str | None:
    parsed = _parse_time_value(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _observe_ingest_metrics(*, metric: str, rows: int, started_at: float) -> None:
    """Record one completed batch after validation and persistence succeed."""
    INGEST_BATCHES.labels(metric=metric).inc()
    INGEST_ROWS.labels(metric=metric).inc(rows)
    INGEST_DURATION.labels(metric=metric).observe(perf_counter() - started_at)


def _schedule_anomaly_check_if_enabled(
    request: Request, background_tasks: BackgroundTasks | None, records: int
) -> None:
    """Schedule a post-ingest anomaly check when Phase 2 config opts in."""
    if records <= 0 or background_tasks is None:
        return
    state = getattr(getattr(request, "app", None), "state", None)
    config = getattr(state, "analysis_config", None)
    engine = getattr(state, "analysis_engine", None)
    if config is None or engine is None:
        return
    anomaly = config.analysis.anomaly_detection
    if anomaly.enabled and anomaly.on_ingest:
        background_tasks.add_task(engine.run_anomaly_check)
