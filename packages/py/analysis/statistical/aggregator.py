"""Time-period data summarization over an injected Observation fetcher.

Summarizes a lookback window for a curated set of scalar metrics, comparing
each against a 30-day personal baseline. The caller supplies the storage-backed
fetcher, keeping this module focused on orchestration and delta math.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..types import PeriodSummary

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    MetricWindowSummarizer = Callable[[str, datetime, datetime], Awaitable[dict[str, Any]]]

# Curated scalar metrics summarized by default — real ontology metric_ids
# (see contracts/ontology.py) that Apple Watch / HealthKit populate. A metric
# that is non-numeric or has no data simply returns zero samples and is
# omitted, so this list is safe to extend.
_DEFAULT_SUMMARY_METRICS: tuple[str, ...] = (
    "vital.heart_rate",
    "vital.resting_heart_rate",
    "vital.hrv_sdnn",
    "vital.respiratory_rate",
    "vital.blood_oxygen",
    "vital.walking_heart_rate_average",
    "activity.steps",
    "activity.active_energy",
    "activity.exercise_minutes",
    "body.weight",
)

# The personal-baseline window every metric is compared against.
_BASELINE_DAYS = 30


class DataAggregator:
    """Produce LLM-digestible period summaries from metric windows."""

    def __init__(self, summarize_metric_window: MetricWindowSummarizer) -> None:
        """Store a fetcher returning avg/min/max/count for one metric window."""
        self._summarize_metric_window = summarize_metric_window

    async def summarize_period(
        self,
        period: str = "daily",
        days: int = 1,
        *,
        metrics: Sequence[str] | None = None,
    ) -> PeriodSummary:
        """Summarize the ``days``-back window into a structured :class:`PeriodSummary`.

        For each metric in ``metrics`` (default :data:`_DEFAULT_SUMMARY_METRICS`)
        compute window avg/min/max/count and a %-deviation against the 30-day
        baseline. Metrics with no samples in the window are omitted; an empty
        ``metrics`` dict signals the engine to skip the run (no LLM call) — the
        same short-circuit the HR/HRV path used.
        """
        metric_ids = tuple(metrics) if metrics is not None else _DEFAULT_SUMMARY_METRICS
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        baseline_start = end - timedelta(days=_BASELINE_DAYS)

        summarized: dict[str, dict[str, Any]] = {}
        for metric_id in metric_ids:
            window = await self._summarize_metric_window(metric_id, start, end)
            if window["count"] == 0:
                continue

            baseline = await self._summarize_metric_window(metric_id, baseline_start, start)
            delta_pct: float | None = None
            if baseline["count"] > 0 and baseline["avg"]:
                delta_pct = ((window["avg"] - baseline["avg"]) / baseline["avg"]) * 100

            summarized[metric_id] = {
                "avg": window["avg"],
                "min": window["min"],
                "max": window["max"],
                "sample_count": window["count"],
                "baseline_avg": baseline["avg"] if baseline["count"] > 0 else None,
                "delta_pct_vs_baseline": delta_pct,
            }

        return PeriodSummary(
            period=period,
            period_start=start,
            period_end=end,
            metrics=summarized,
        )
