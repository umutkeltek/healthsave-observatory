"""Trend analysis - linear regression over daily aggregates.

Phase 5F lifted the SQL out of this module into
``storage.timescale.analysis``. Statistical machinery (regression,
sufficiency gates, day coercion) stays here; data access is delegated
through the lazy ``_sql()`` handle (see :func:`analysis.engine._sql`
for the cycle background).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..types import Trend
from .gates import MINIMUM_DATA_REQUIREMENTS

_SUPPORTED_METRICS = frozenset({"heart_rate", "hrv"})
_SIGNIFICANCE_P = 0.05
_HIGH_CONFIDENCE_P = 0.01


def _sql():
    """Lazy import handle for ``storage.timescale.analysis`` — see
    :func:`analysis.engine._sql` for the cycle background.
    """
    from storage.timescale import analysis as analysis_sql

    return analysis_sql


class TrendAnalyzer:
    """Detect multi-day/multi-week trends via linear regression."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def analyze(self, metric: str, days: int = 30) -> Trend | None:
        """Return a significant trend for ``metric`` over the window, or None.

        Phase 2b supports ``heart_rate`` and ``hrv``. Heart rate uses the
        ``hr_hourly`` continuous aggregate with a raw ``heart_rate`` fallback
        for fresh installs. HRV uses the raw ``hrv`` hypertable.
        """
        if metric not in _SUPPORTED_METRICS:
            raise ValueError(f"Unsupported trend metric: {metric}")

        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)

        async with self.session_factory() as session:
            rows = await self._fetch_daily_values(session, metric, start, end)

        if not _has_sufficient_data(rows):
            return None

        points = _regression_points(rows)
        if len(points) < 2:
            return None

        # Deferred import keeps module import cheap for users who keep trend
        # analysis disabled, while still using SciPy for the actual math.
        from scipy.stats import linregress

        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        result = linregress(x_values, y_values)

        if result.pvalue >= _SIGNIFICANCE_P or result.slope == 0:
            return None

        return Trend(
            metric=metric,
            slope=float(result.slope),
            direction="up" if result.slope > 0 else "down",
            period_days=days,
            p_value=float(result.pvalue),
            confidence="high" if result.pvalue < _HIGH_CONFIDENCE_P else "medium",
        )

    async def _fetch_daily_values(
        self, session, metric: str, start: datetime, end: datetime
    ) -> list[Any]:
        if metric == "heart_rate":
            rows = await _sql().fetch_heart_rate_daily_from_hourly(session, start, end)
            if rows:
                return rows
            return await _sql().fetch_heart_rate_daily_from_raw(session, start, end)
        return await _sql().fetch_hrv_daily(session, start, end)


def _has_sufficient_data(rows: list[Any]) -> bool:
    requirements = MINIMUM_DATA_REQUIREMENTS["trend_analysis"]
    days_with_data = {
        _coerce_day(row.day)
        for row in rows
        if getattr(row, "value", None) is not None and getattr(row, "day", None) is not None
    }
    return (
        len(rows) >= requirements["min_observations"]
        and len(days_with_data) >= requirements["min_days"]
    )


def _regression_points(rows: list[Any]) -> list[tuple[int, float]]:
    usable = [
        (_coerce_day(row.day), float(row.value))
        for row in rows
        if getattr(row, "value", None) is not None and getattr(row, "day", None) is not None
    ]
    usable.sort(key=lambda item: item[0])
    if not usable:
        return []
    first_day = usable[0][0]
    return [((day - first_day).days, value) for day, value in usable]


def _coerce_day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
