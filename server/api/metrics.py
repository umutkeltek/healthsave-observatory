"""Prometheus metrics endpoint and shared metric collectors."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from prometheus_client.metrics import MetricWrapperBase

router = APIRouter()

INGEST_BATCHES = Counter(
    "hdh_ingest_batches",
    "Number of ingest batches accepted by the API.",
    ["metric"],
)
INGEST_ROWS = Counter(
    "hdh_ingest_rows",
    "Number of rows processed by the ingest API.",
    ["metric"],
)
AI_BRIEFING_RUNS = Counter(
    "hdh_ai_briefing_runs",
    "Analysis job runs partitioned by job and result.",
    ["job", "result"],
)
INGEST_DURATION = Histogram(
    "hdh_ingest_duration_seconds",
    "End-to-end ingest handler duration in seconds.",
    ["metric"],
)


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def reset_metrics() -> None:
    """Clear label children so tests start from a deterministic registry state."""
    _reset_metric_children(INGEST_BATCHES)
    _reset_metric_children(INGEST_ROWS)
    _reset_metric_children(AI_BRIEFING_RUNS)
    _reset_metric_children(INGEST_DURATION)


def _reset_metric_children(metric: MetricWrapperBase) -> None:
    with metric._lock:
        metric._metrics.clear()
