"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from observability.metrics import (
    AI_BRIEFING_RUNS,
    CANONICAL_DUAL_WRITE,
    INGEST_BATCHES,
    INGEST_DURATION,
    INGEST_REJECTED,
    INGEST_ROWS,
    LEDGER_LISTENER_FAILURES,
    PIPELINE_RUNS_LEDGER_FAILURES,
    RAW_LOG_ORPHANED,
    STATUS_QUERY_FAILURES,
    SYNC_RECEIPT_WRITE_FAILURES,
    reset_metrics,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()

__all__ = [
    "AI_BRIEFING_RUNS",
    "CANONICAL_DUAL_WRITE",
    "INGEST_BATCHES",
    "INGEST_DURATION",
    "INGEST_REJECTED",
    "INGEST_ROWS",
    "LEDGER_LISTENER_FAILURES",
    "PIPELINE_RUNS_LEDGER_FAILURES",
    "RAW_LOG_ORPHANED",
    "STATUS_QUERY_FAILURES",
    "SYNC_RECEIPT_WRITE_FAILURES",
    "prometheus_metrics",
    "reset_metrics",
    "router",
]


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
