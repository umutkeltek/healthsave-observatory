"""POST /api/apple/batch — receive a metric batch from a HealthSave client."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
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
async def apple_batch(request: Request, session: AsyncSession = Depends(get_session)):
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
    log.info(f"Ingested {count} records for {metric} (batch {batch_idx + 1}/{total})")

    return {
        "status": "processed",
        "metric": metric,
        "batch": batch_idx,
        "total_batches": total,
        "records": count,
    }
