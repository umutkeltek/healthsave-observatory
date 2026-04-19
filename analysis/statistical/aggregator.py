"""Time-period data summarization.

Phase 2 scope: heart-rate **and HRV**. HR uses the ``hr_hourly``
continuous aggregate with a raw ``heart_rate`` fallback for fresh
installs. HRV has no continuous aggregate, so the raw ``hrv`` table is
the primary path - Apple Watch only records 5-30 HRV samples per day,
so aggregating raw rows directly is fine at MVP scale (30 days of data
is well under 5000 rows).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from ..types import PeriodSummary


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
            yesterday_hr = await self._hr_summary(session, start, end)
            if yesterday_hr["count"] == 0:
                yesterday_hr = await self._raw_hr_summary(session, start, end)

            baseline_hr: dict[str, Any] | None = None
            if yesterday_hr["count"] > 0:
                baseline_hr = await self._hr_summary(session, baseline_start, start)
                if baseline_hr["count"] == 0:
                    baseline_hr = await self._raw_hr_summary(session, baseline_start, start)

            # ─── HRV ────────────────────────────────────────────────
            yesterday_hrv = await self._hrv_summary(session, start, end)
            baseline_hrv: dict[str, Any] | None = None
            if yesterday_hrv["count"] > 0:
                baseline_hrv = await self._hrv_summary(session, baseline_start, start)

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

    async def _hr_summary(self, session, start: datetime, end: datetime) -> dict[str, Any]:
        """Aggregate ``hr_hourly`` over ``[start, end)`` into avg/min/max/count."""
        result = await session.execute(
            text(
                """
                SELECT avg(avg_bpm)::float AS avg_v,
                       min(min_bpm) AS min_v,
                       max(max_bpm) AS max_v,
                       sum(samples) AS count_v
                FROM hr_hourly
                WHERE bucket >= :start AND bucket < :end
                """
            ),
            {"start": start, "end": end},
        )
        row = result.fetchone()
        if row is None:
            return {"avg": None, "min": None, "max": None, "count": 0}
        return {
            "avg": row.avg_v,
            "min": row.min_v,
            "max": row.max_v,
            "count": row.count_v or 0,
        }

    async def _raw_hr_summary(self, session, start: datetime, end: datetime) -> dict[str, Any]:
        """Aggregate raw ``heart_rate`` rows when ``hr_hourly`` has not refreshed."""
        result = await session.execute(
            text(
                """
                SELECT avg(bpm)::float AS avg_v,
                       min(bpm) AS min_v,
                       max(bpm) AS max_v,
                       count(*) AS count_v
                FROM heart_rate
                WHERE time >= :start AND time < :end
                """
            ),
            {"start": start, "end": end},
        )
        row = result.fetchone()
        if row is None:
            return {"avg": None, "min": None, "max": None, "count": 0}
        return {
            "avg": row.avg_v,
            "min": row.min_v,
            "max": row.max_v,
            "count": row.count_v or 0,
        }

    async def _hrv_summary(self, session, start: datetime, end: datetime) -> dict[str, Any]:
        """Aggregate raw ``hrv`` rows over ``[start, end)`` into avg/min/max/count.

        HRV has no continuous aggregate (D11) because Apple Watch records
        only 5-30 samples per day - aggregating the raw hypertable
        directly is fast enough for MVP windows.
        """
        result = await session.execute(
            text(
                """
                SELECT avg(value_ms)::float AS avg_v,
                       min(value_ms) AS min_v,
                       max(value_ms) AS max_v,
                       count(*) AS count_v
                FROM hrv
                WHERE time >= :start AND time < :end
                """
            ),
            {"start": start, "end": end},
        )
        row = result.fetchone()
        if row is None:
            return {"avg": None, "min": None, "max": None, "count": 0}
        return {
            "avg": row.avg_v,
            "min": row.min_v,
            "max": row.max_v,
            "count": row.count_v or 0,
        }
