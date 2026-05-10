"""POST /api/apple/batch - receive a metric batch from a HealthSave client."""

import logging
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from ..ingestion.parsers import group_samples_by_device
from ..ingestion.storage import (
    AuditLog,
    IngestStorage,
    default_audit_log,
    default_storage,
)
from ..models.batch import BatchPayload
from .deps import get_session, verify_api_key
from .metrics import INGEST_BATCHES, INGEST_DURATION, INGEST_ROWS

log = logging.getLogger("healthsave")

router = APIRouter()


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
    count = 0

    for device_name, device_samples in sample_groups:
        device_id = (
            first_device_id
            if device_name == first_device_name
            else await storage.get_or_create_device(session, device_name)
        )
        count += await storage.ingest_metric(session, device_id, metric, device_samples, owner_id)

    if audit and raw_log_id is not None:
        await audit.mark_processed(session, raw_log_id)
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
