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

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from compat_v1.models import BatchPayload
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale.sync_receipts import record_sync_receipt

from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from ..ingestion.parsers import group_samples_by_device
from ..ingestion.storage import (
    AuditLog,
    IngestStorage,
    default_audit_log,
    default_storage,
)
from .deps import get_session, verify_api_key
from .metrics import INGEST_BATCHES, INGEST_DURATION, INGEST_ROWS, RAW_LOG_ORPHANED

if TYPE_CHECKING:
    from plugin_sdk import Source

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
    raw_payload = await request.json()
    try:
        payload = BatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    try:
        owner_id = resolve_owner_id(request.headers.get(OWNER_HEADER))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {OWNER_HEADER}: {exc}") from exc

    storage = _resolve_storage(request)
    audit = _resolve_audit_log(request)

    metric = payload.metric.strip() or "unknown"
    batch_idx = payload.batch_index
    total = payload.total_batches
    samples = payload.samples

    if not samples:
        raw_log_id = await audit.log_raw(session, None, raw_payload) if audit else None
        await _record_sync_receipt(
            session,
            request=request,
            metric=metric,
            batch_index=batch_idx,
            total_batches=total,
            status="empty",
            records_accepted=0,
            records_skipped=0,
            raw_log_id=raw_log_id,
        )
        await session.commit()
        if audit and raw_log_id is not None:
            await audit.mark_processed(session, raw_log_id)
            await session.commit()
        _observe_ingest_metrics(metric=metric, rows=0, started_at=started_at)
        return {"status": "empty", "metric": metric, "batch": batch_idx, "records": 0}

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
        result = await plugin.ingest(
            {
                "storage": storage,
                "session": session,
                "device_id": first_device_id,
                "first_device_name": first_device_name,
                "metric": metric,
                "samples": samples,
                "owner_id": owner_id,
            }
        )
        count = result["accepted"]
    except Exception:
        try:
            RAW_LOG_ORPHANED.labels(metric=metric).inc()
        except Exception:  # pragma: no cover - metrics import optional
            log.debug("failed to record RAW_LOG_ORPHANED{metric=%s}", metric)
        await session.rollback()
        log.exception("ingest loop failed for %s; raw_log_id=%s left orphaned", metric, raw_log_id)
        raise

    if audit and raw_log_id is not None:
        await audit.mark_processed(session, raw_log_id)
    await _record_sync_receipt(
        session,
        request=request,
        metric=metric,
        batch_index=batch_idx,
        total_batches=total,
        status="processed",
        records_accepted=count,
        records_skipped=max(len(samples) - count, 0),
        raw_log_id=raw_log_id,
    )
    await session.commit()
    _observe_ingest_metrics(metric=metric, rows=count, started_at=started_at)
    log.info("Ingested %d records for %s (batch %d/%d)", count, metric, batch_idx + 1, total)
    _schedule_anomaly_check_if_enabled(request, background_tasks, count)

    return {
        "status": "processed",
        "metric": metric,
        "batch": batch_idx,
        "total_batches": total,
        "records": count,
    }


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


async def _record_sync_receipt(
    session: AsyncSession,
    *,
    request: Request,
    metric: str,
    batch_index: int,
    total_batches: int,
    status: str,
    records_accepted: int,
    records_skipped: int,
    raw_log_id: int | None,
    error_message: str | None = None,
) -> None:
    """Persist the HealthSave sync headers that released iOS already sends."""

    headers = request.headers
    sync_run_id = _header(headers, "X-HealthSave-Sync-Run-ID")
    batch_id = _header(headers, "X-HealthSave-Batch-ID")
    payload_hash = _header(headers, "X-HealthSave-Payload-Hash")
    header_metric = _header(headers, "X-HealthSave-Metric")

    await record_sync_receipt(
        session,
        sync_run_id=sync_run_id,
        batch_id=batch_id,
        payload_hash=payload_hash,
        metric=header_metric or metric,
        batch_index=_header_int(headers, "X-HealthSave-Batch-Index", batch_index),
        total_batches=_header_int(headers, "X-HealthSave-Total-Batches", total_batches),
        status=status,
        records_accepted=records_accepted,
        records_skipped=records_skipped,
        raw_log_id=raw_log_id,
        error_message=error_message,
    )


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
