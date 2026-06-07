"""Prometheus collectors shared by app services and package code."""

from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_client.metrics import MetricWrapperBase

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
CANONICAL_DUAL_WRITE = Counter(
    "hdh_canonical_dual_write",
    "v2 canonical_observations dual-write outcomes from /api/apple/batch. "
    "result=ok counts observations written; rejected counts unmapped/invalid "
    "samples; error counts a GUARDED canonical-side failure that left the v1 "
    "path and its response untouched (Decision C migration bridge).",
    ["metric", "result"],
)
SYNC_RECEIPT_WRITE_FAILURES = Counter(
    "hdh_sync_receipt_write_failures",
    "Delivery-receipt writes that failed AFTER a successful ingest commit "
    "(CONTRACT-002). The health data IS persisted; only the /api/v2/sync receipt "
    "row is missing. Non-zero means sync-history accounting is incomplete for "
    "that metric even though ingestion succeeded.",
    ["metric"],
)


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
    _reset_metric_children(CANONICAL_DUAL_WRITE)
    _reset_metric_children(SYNC_RECEIPT_WRITE_FAILURES)


def _reset_metric_children(metric: MetricWrapperBase) -> None:
    with metric._lock:
        metric._metrics.clear()
