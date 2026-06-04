"""Unit tests for :class:`analysis.statistical.trends.TrendAnalyzer`.

The trend analyzer follows the no-live-DB discipline: tests queue fake daily
value rowsets and assert behavior from those rows.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.statistical.trends import TrendAnalyzer  # noqa: E402


class _Row(SimpleNamespace):
    """Lightweight row stub - attribute access mimics SQLAlchemy ``Row``."""


class _DailyValueFetcher:
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls: list[tuple[str, object, object]] = []

    async def __call__(self, metric, start, end):
        self.calls.append((metric, start, end))
        return self._batches.pop(0) if self._batches else []


def _daily_rows(*, start: date, values: list[float]) -> list[_Row]:
    return [
        _Row(day=start + timedelta(days=index), value=value, sample_count=24)
        for index, value in enumerate(values)
    ]


@pytest.mark.asyncio
async def test_analyze_uses_injected_daily_value_fetcher_without_session():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[60.0 + (index * 0.5) for index in range(30)],
    )
    calls: list[tuple[str, object, object]] = []

    async def fetch_daily_values(metric, start, end):
        calls.append((metric, start, end))
        return rows

    trend = await TrendAnalyzer(fetch_daily_values).analyze("heart_rate", days=30)

    assert trend is not None
    assert trend.metric == "heart_rate"
    assert trend.slope == pytest.approx(0.5, rel=1e-6)
    assert [call[0] for call in calls] == ["heart_rate"]


@pytest.mark.asyncio
async def test_analyze_detects_significant_upward_heart_rate_trend():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[60.0 + (index * 0.5) for index in range(30)],
    )
    fetch_daily_values = _DailyValueFetcher([rows])

    trend = await TrendAnalyzer(fetch_daily_values).analyze("heart_rate", days=30)

    assert trend is not None
    assert trend.metric == "heart_rate"
    assert trend.direction == "up"
    assert trend.period_days == 30
    assert trend.slope == pytest.approx(0.5, rel=1e-6)
    assert trend.p_value is not None
    assert trend.p_value < 0.05
    assert trend.confidence == "high"
    assert fetch_daily_values.calls[0][0] == "heart_rate"


@pytest.mark.asyncio
async def test_analyze_detects_significant_downward_heart_rate_trend():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[72.0 - (index * 0.25) for index in range(30)],
    )
    fetch_daily_values = _DailyValueFetcher([rows])

    trend = await TrendAnalyzer(fetch_daily_values).analyze("heart_rate", days=30)

    assert trend is not None
    assert trend.direction == "down"
    assert trend.slope == pytest.approx(-0.25, rel=1e-6)


@pytest.mark.asyncio
async def test_analyze_detects_significant_downward_hrv_trend():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[80.0 - index for index in range(30)],
    )
    fetch_daily_values = _DailyValueFetcher([rows])

    trend = await TrendAnalyzer(fetch_daily_values).analyze("hrv", days=30)

    assert trend is not None
    assert trend.metric == "hrv"
    assert trend.direction == "down"
    assert trend.slope == pytest.approx(-1.0, rel=1e-6)
    assert trend.p_value is not None
    assert trend.p_value < 0.05
    assert fetch_daily_values.calls[0][0] == "hrv"


@pytest.mark.asyncio
async def test_analyze_returns_none_when_data_is_below_trend_sufficiency_gate():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[60.0 + (index * 0.5) for index in range(20)],
    )
    fetch_daily_values = _DailyValueFetcher([rows])

    trend = await TrendAnalyzer(fetch_daily_values).analyze("heart_rate", days=30)

    assert trend is None


@pytest.mark.asyncio
async def test_analyze_returns_none_when_regression_is_not_significant():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[
            70.0,
            65.0,
            74.0,
            61.0,
            76.0,
            63.0,
            72.0,
            66.0,
            75.0,
            62.0,
            71.0,
            64.0,
            73.0,
            67.0,
            70.5,
            65.5,
            74.5,
            61.5,
            76.5,
            63.5,
            72.5,
            66.5,
            75.5,
            62.5,
            71.5,
            64.5,
            73.5,
            67.5,
            69.0,
            68.0,
        ],
    )
    fetch_daily_values = _DailyValueFetcher([rows])

    trend = await TrendAnalyzer(fetch_daily_values).analyze("heart_rate", days=30)

    assert trend is None
