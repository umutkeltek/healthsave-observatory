"""Unit tests for :class:`analysis.statistical.aggregator.DataAggregator`.

Extends the Phase 1 ``FakeSession`` discipline from
``test_api_contract.py``: no live DB, every SQL call short-circuited by
canned fakes so the aggregator's window math + delta calculation can be
exercised deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.statistical.aggregator import DataAggregator  # noqa: E402


class _Row:
    """Row stub mimicking SQLAlchemy's ``Row`` attribute access."""

    def __init__(self, avg_v, min_v, max_v, count_v):
        self.avg_v = avg_v
        self.min_v = min_v
        self.max_v = max_v
        self.count_v = count_v


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSession:
    """Async context manager + async execute that returns queued rows."""

    def __init__(self, queue):
        self._queue = list(queue)
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        row = self._queue.pop(0) if self._queue else None
        return _Result(row)


def _session_factory(rows):
    session = _FakeSession(rows)

    def factory():
        return session

    factory.session = session  # expose for assertions
    return factory


@pytest.mark.asyncio
async def test_summarize_period_computes_delta_vs_baseline():
    yesterday = _Row(avg_v=65.0, min_v=55, max_v=120, count_v=24)
    baseline = _Row(avg_v=62.0, min_v=50, max_v=140, count_v=720)
    factory = _session_factory([yesterday, baseline])

    summary = await DataAggregator(factory).summarize_period("daily", 1)

    hr = summary.metrics["heart_rate"]
    assert hr["avg_bpm"] == 65.0
    assert hr["min_bpm"] == 55
    assert hr["max_bpm"] == 120
    assert hr["sample_count"] == 24
    assert hr["baseline_avg_bpm"] == 62.0
    assert hr["delta_pct_vs_baseline"] == pytest.approx(4.8387, rel=1e-3)
    assert summary.period == "daily"


@pytest.mark.asyncio
async def test_summarize_period_returns_empty_when_yesterday_has_no_data():
    yesterday = _Row(avg_v=None, min_v=None, max_v=None, count_v=0)
    raw_yesterday = _Row(avg_v=None, min_v=None, max_v=None, count_v=0)
    factory = _session_factory([yesterday, raw_yesterday])

    summary = await DataAggregator(factory).summarize_period("daily", 1)

    assert summary.metrics == {}
    assert summary.period == "daily"


@pytest.mark.asyncio
async def test_summarize_period_handles_missing_baseline():
    """Yesterday has data but baseline window is empty (e.g. fresh install)."""
    yesterday = _Row(avg_v=70.0, min_v=58, max_v=110, count_v=24)
    baseline = _Row(avg_v=None, min_v=None, max_v=None, count_v=0)
    raw_baseline = _Row(avg_v=None, min_v=None, max_v=None, count_v=0)
    factory = _session_factory([yesterday, baseline, raw_baseline])

    summary = await DataAggregator(factory).summarize_period("daily", 1)

    hr = summary.metrics["heart_rate"]
    assert hr["avg_bpm"] == 70.0
    assert hr["baseline_avg_bpm"] is None
    assert hr["delta_pct_vs_baseline"] is None


@pytest.mark.asyncio
async def test_summarize_period_falls_back_to_raw_heart_rate_when_hourly_view_is_empty():
    empty_hourly = _Row(avg_v=None, min_v=None, max_v=None, count_v=0)
    raw_yesterday = _Row(avg_v=72.0, min_v=60, max_v=128, count_v=1440)
    baseline = _Row(avg_v=68.0, min_v=50, max_v=140, count_v=720)
    factory = _session_factory([empty_hourly, raw_yesterday, baseline])

    summary = await DataAggregator(factory).summarize_period("daily", 1)

    hr = summary.metrics["heart_rate"]
    assert hr["avg_bpm"] == 72.0
    assert hr["sample_count"] == 1440
    assert hr["baseline_avg_bpm"] == 68.0
    queries = [sql for sql, _ in factory.session.calls]
    assert any("FROM hr_hourly" in sql for sql in queries)
    assert any("FROM heart_rate" in sql for sql in queries)
