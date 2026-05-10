"""Time-period data summarization.

Phase 2 scope: heart-rate **and HRV**. HR uses the ``hr_hourly``
continuous aggregate with a raw ``heart_rate`` fallback for fresh
installs. HRV has no continuous aggregate, so the raw ``hrv`` table is
the primary path - Apple Watch only records 5-30 HRV samples per day,
so aggregating raw rows directly is fine at MVP scale (30 days of data
is well under 5000 rows).

Phase 5F lifted the SQL out of this module into
``storage.timescale.analysis``. The ``DataAggregator`` orchestrator
below stays in the analysis layer; SQL access is delegated through
the lazy ``_sql()`` handle to avoid the import cycle that bit Phase
5C/5E (see ``analysis.engine._sql`` for the full trace).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..types import PeriodSummary


def _sql():
    """Lazy import handle for ``storage.timescale.analysis`` — see
    :func:`analysis.engine._sql` for the cycle background.
    """
    from storage.timescale import analysis as analysis_sql

    return analysis_sql


class DataAggregator:
    """Produce LLM-digestible period summaries from TimescaleDB."""

    def __init__(self, session_factory) -> None:
        """Store the async sessionmaker (or any async context factory)."""
        self.session_factory = session_factory

    async def summarize_period(self, period: str = "daily", days: int = 1) -> PeriodSummary:
        """Summarize a lookback window into a structured :class:`PeriodSummary`.

        MVP computes yesterday's heart-rate + HRV window (``days`` back,
        default 1) against a 30-day baseline. Returns an empty-metrics
        :class:`PeriodSummary` when BOTH lookback metrics have no samples
        - the engine uses this to short-circuit the LLM call and record
        the run as ``skipped``. When only HR or only HRV is present, the
        returned ``metrics`` dict includes just the non-empty metric.
        """
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        baseline_start = end - timedelta(days=30)

        async with self.session_factory() as session:
            # ─── Heart rate ─────────────────────────────────────────
            yesterday_hr = await _sql().hr_summary_from_hourly(session, start, end)
            if yesterday_hr["count"] == 0:
                yesterday_hr = await _sql().hr_summary_from_raw(session, start, end)

            baseline_hr: dict[str, Any] | None = None
            if yesterday_hr["count"] > 0:
                baseline_hr = await _sql().hr_summary_from_hourly(session, baseline_start, start)
                if baseline_hr["count"] == 0:
                    baseline_hr = await _sql().hr_summary_from_raw(session, baseline_start, start)

            # ─── HRV ────────────────────────────────────────────────
            yesterday_hrv = await _sql().hrv_summary(session, start, end)
            baseline_hrv: dict[str, Any] | None = None
            if yesterday_hrv["count"] > 0:
                baseline_hrv = await _sql().hrv_summary(session, baseline_start, start)

        metrics: dict[str, dict[str, Any]] = {}

        if yesterday_hr["count"] > 0:
            delta_pct_hr: float | None = None
            if baseline_hr and baseline_hr["count"] > 0 and baseline_hr["avg"]:
                delta_pct_hr = (
                    (yesterday_hr["avg"] - baseline_hr["avg"]) / baseline_hr["avg"]
                ) * 100
            metrics["heart_rate"] = {
                "avg_bpm": yesterday_hr["avg"],
                "min_bpm": yesterday_hr["min"],
                "max_bpm": yesterday_hr["max"],
                "sample_count": yesterday_hr["count"],
                "baseline_avg_bpm": baseline_hr["avg"] if baseline_hr else None,
                "delta_pct_vs_baseline": delta_pct_hr,
            }

        if yesterday_hrv["count"] > 0:
            delta_pct_hrv: float | None = None
            if baseline_hrv and baseline_hrv["count"] > 0 and baseline_hrv["avg"]:
                delta_pct_hrv = (
                    (yesterday_hrv["avg"] - baseline_hrv["avg"]) / baseline_hrv["avg"]
                ) * 100
            metrics["hrv"] = {
                "avg_ms": yesterday_hrv["avg"],
                "min_ms": yesterday_hrv["min"],
                "max_ms": yesterday_hrv["max"],
                "sample_count": yesterday_hrv["count"],
                "baseline_avg_ms": baseline_hrv["avg"] if baseline_hrv else None,
                "delta_pct_vs_baseline": delta_pct_hrv,
            }

        return PeriodSummary(
            period=period,
            period_start=start,
            period_end=end,
            metrics=metrics,
        )
