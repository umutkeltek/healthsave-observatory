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
INGEST_REJECTED = Counter(
    "hdh_ingest_rejected_rows",
    "Per-batch rows that the ingest path silently dropped (parse failure, missing field, "
    "wrong type). Phase 5G surfaced this — pre-5G these were invisible.",
    ["metric", "reason"],
)
RAW_LOG_ORPHANED = Counter(
    "hdh_raw_log_orphaned",
    "Raw_ingestion_log rows left with processed=false because the metric ingest loop "
    "raised mid-batch. Each increment is a row that needs operator attention.",
    ["metric"],
)
STATUS_QUERY_FAILURES = Counter(
    "hdh_status_query_failures",
    "GET /api/apple/status per-metric query failures. Each non-zero value is masked "
    "behind a {count:0} response to preserve the iOS contract; this counter is the "
    "operator-side signal.",
    ["metric", "exception"],
)
PIPELINE_RUNS_LEDGER_FAILURES = Counter(
    "hdh_pipeline_runs_ledger_failures",
    "Failures writing to the pipeline_runs ledger from the API insights/trigger path. "
    "A non-zero value means a triggered run completed but its ledger row is missing or "
    "wrong; user got 200 OK while observability silently degraded.",
    ["phase"],
)
LEDGER_LISTENER_FAILURES = Counter(
    "hdh_ledger_listener_failures",
    "Failures inside the worker's APScheduler listener that records pipeline_runs rows. "
    "Phases: claim (INSERT failed), lookup_missing (claim row never landed before "
    "complete event), mark_succeeded / mark_failed (UPDATE failed). Pair with the "
    "stuck-run reaper for full coverage.",
    ["phase"],
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
    _reset_metric_children(INGEST_REJECTED)
    _reset_metric_children(RAW_LOG_ORPHANED)
    _reset_metric_children(STATUS_QUERY_FAILURES)
    _reset_metric_children(PIPELINE_RUNS_LEDGER_FAILURES)
    _reset_metric_children(LEDGER_LISTENER_FAILURES)


def _reset_metric_children(metric: MetricWrapperBase) -> None:
    with metric._lock:
        metric._metrics.clear()
