"""Unit tests for :class:`analysis.statistical.trends.TrendAnalyzer`.

The trend analyzer follows the existing no-live-DB discipline: tests
queue fake SQL rowsets and assert behavior from those rows.
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


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        rows = self._batches.pop(0) if self._batches else []
        return _Result(rows)


def _session_factory(batches):
    session = _FakeSession(batches)

    def factory():
        return session

    factory.session = session
    return factory


def _daily_rows(*, start: date, values: list[float]) -> list[_Row]:
    return [
        _Row(day=start + timedelta(days=index), value=value, sample_count=24)
        for index, value in enumerate(values)
    ]


@pytest.mark.asyncio
async def test_analyze_detects_significant_upward_heart_rate_trend():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[60.0 + (index * 0.5) for index in range(30)],
    )
    factory = _session_factory([rows])

    trend = await TrendAnalyzer(factory).analyze("heart_rate", days=30)

    assert trend is not None
    assert trend.metric == "heart_rate"
    assert trend.direction == "up"
    assert trend.period_days == 30
    assert trend.slope == pytest.approx(0.5, rel=1e-6)
    assert trend.p_value is not None
    assert trend.p_value < 0.05
    assert trend.confidence == "high"
    assert "FROM hr_hourly" in factory.session.calls[0][0]


@pytest.mark.asyncio
async def test_analyze_falls_back_to_raw_heart_rate_when_hourly_view_is_empty():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[72.0 - (index * 0.25) for index in range(30)],
    )
    factory = _session_factory([[], rows])

    trend = await TrendAnalyzer(factory).analyze("heart_rate", days=30)

    assert trend is not None
    assert trend.direction == "down"
    assert trend.slope == pytest.approx(-0.25, rel=1e-6)
    queries = [sql for sql, _ in factory.session.calls]
    assert any("FROM hr_hourly" in sql for sql in queries)
    assert any("FROM heart_rate" in sql for sql in queries)


@pytest.mark.asyncio
async def test_analyze_detects_significant_downward_hrv_trend():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[80.0 - index for index in range(30)],
    )
    factory = _session_factory([rows])

    trend = await TrendAnalyzer(factory).analyze("hrv", days=30)

    assert trend is not None
    assert trend.metric == "hrv"
    assert trend.direction == "down"
    assert trend.slope == pytest.approx(-1.0, rel=1e-6)
    assert trend.p_value is not None
    assert trend.p_value < 0.05
    assert "FROM hrv" in factory.session.calls[0][0]


@pytest.mark.asyncio
async def test_analyze_returns_none_when_data_is_below_trend_sufficiency_gate():
    rows = _daily_rows(
        start=date(2026, 3, 1),
        values=[60.0 + (index * 0.5) for index in range(20)],
    )
    factory = _session_factory([rows])

    trend = await TrendAnalyzer(factory).analyze("heart_rate", days=30)

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
    factory = _session_factory([rows])

    trend = await TrendAnalyzer(factory).analyze("heart_rate", days=30)

    assert trend is None
