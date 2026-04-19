"""Time-period data summarization.

Phase 1.5 MVP scope: heart-rate only. The primary path uses the
``hr_hourly`` continuous aggregate, with a raw ``heart_rate`` fallback for
fresh installs where TimescaleDB has not refreshed the aggregate yet.
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

        MVP computes yesterday's heart-rate window (``days`` back, default
        1) against a 30-day baseline.
        Returns an empty-metrics :class:`PeriodSummary` when the lookback
        window has no samples — the engine uses this to short-circuit the
        LLM call and record the run as ``skipped``.
        """
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        baseline_start = end - timedelta(days=30)

        async with self.session_factory() as session:
            yesterday = await self._hr_summary(session, start, end)
            if yesterday["count"] == 0:
                yesterday = await self._raw_hr_summary(session, start, end)

            if yesterday["count"] == 0:
                return PeriodSummary(
                    period=period,
                    period_start=start,
                    period_end=end,
                    metrics={},
                )

            baseline = await self._hr_summary(session, baseline_start, start)
            if baseline["count"] == 0:
                baseline = await self._raw_hr_summary(session, baseline_start, start)

        delta_pct: float | None = None
        if baseline["count"] > 0 and baseline["avg"]:
            delta_pct = ((yesterday["avg"] - baseline["avg"]) / baseline["avg"]) * 100

        heart_rate: dict[str, Any] = {
            "avg_bpm": yesterday["avg"],
            "min_bpm": yesterday["min"],
            "max_bpm": yesterday["max"],
            "sample_count": yesterday["count"],
            "baseline_avg_bpm": baseline["avg"],
            "delta_pct_vs_baseline": delta_pct,
        }

        return PeriodSummary(
            period=period,
            period_start=start,
            period_end=end,
            metrics={"heart_rate": heart_rate},
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
