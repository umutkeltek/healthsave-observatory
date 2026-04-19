"""POST /api/apple/batch — receive a metric batch from a HealthSave client."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingestion.handlers import (
    _get_or_create_device,
    _ingest_metric,
    _log_raw_ingestion,
    _mark_raw_ingestion_processed,
)
from ..ingestion.parsers import group_samples_by_device
from ..models.batch import BatchPayload
from .deps import get_session, verify_api_key

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
    raw_payload = await request.json()
    try:
        payload = BatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    metric = payload.metric.strip() or "unknown"
    batch_idx = payload.batch_index
    total = payload.total_batches
    samples = payload.samples

    if not samples:
        raw_log_id = await _log_raw_ingestion(session, None, raw_payload)
        await session.commit()
        await _mark_raw_ingestion_processed(session, raw_log_id)
        await session.commit()
        return {"status": "empty", "metric": metric, "batch": batch_idx, "records": 0}

    sample_groups = group_samples_by_device(samples)
    first_device_name, _ = sample_groups[0]
    first_device_id = await _get_or_create_device(session, first_device_name)
    raw_log_id = await _log_raw_ingestion(session, first_device_id, raw_payload)
    await session.commit()
    count = 0

    for device_name, device_samples in sample_groups:
        device_id = (
            first_device_id
            if device_name == first_device_name
            else await _get_or_create_device(session, device_name)
        )
        count += await _ingest_metric(session, device_id, metric, device_samples)

    await _mark_raw_ingestion_processed(session, raw_log_id)
    await session.commit()
    log.info("Ingested %d records for %s (batch %d/%d)", count, metric, batch_idx + 1, total)
    _schedule_anomaly_check_if_enabled(request, background_tasks, count)

    return {
        "status": "processed",
        "metric": metric,
        "batch": batch_idx,
        "total_batches": total,
        "records": count,
    }


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
