"""Unit tests for :class:`analysis.statistical.aggregator.DataAggregator`.

FakeSession discipline — no live DB. The aggregator reads the canonical store
via ``summarize_metric_window`` (one window query per metric, plus a baseline
query when the window has data), so each test queues ``_Row`` results in that
order and asserts the generic per-metric summary shape + delta math.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.statistical.aggregator import _DEFAULT_SUMMARY_METRICS, DataAggregator  # noqa: E402


class _Row:
    """Row stub mimicking SQLAlchemy's ``Row`` attribute access."""

    def __init__(self, avg_v, min_v, max_v, count_v):
        self.avg_v = avg_v
        self.min_v = min_v
        self.max_v = max_v
        self.count_v = count_v


def _empty() -> _Row:
    return _Row(avg_v=None, min_v=None, max_v=None, count_v=0)


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
        row = self._queue.pop(0) if self._queue else _empty()
        return _Result(row)


def _session_factory(rows):
    session = _FakeSession(rows)

    def factory():
        return session

    factory.session = session  # expose for assertions
    return factory


@pytest.mark.asyncio
async def test_summarize_period_computes_delta_vs_baseline():
    # One metric: window row then baseline row.
    window = _Row(avg_v=65.0, min_v=55, max_v=120, count_v=24)
    baseline = _Row(avg_v=62.0, min_v=50, max_v=140, count_v=720)
    factory = _session_factory([window, baseline])

    summary = await DataAggregator(factory).summarize_period(
        "daily", 1, metrics=["vital.heart_rate"]
    )

    hr = summary.metrics["vital.heart_rate"]
    assert hr["avg"] == 65.0
    assert hr["min"] == 55
    assert hr["max"] == 120
    assert hr["sample_count"] == 24
    assert hr["baseline_avg"] == 62.0
    assert hr["delta_pct_vs_baseline"] == pytest.approx(4.8387, rel=1e-3)
    assert summary.period == "daily"

    # Reads the canonical store, scoped by metric_id.
    sql, params = factory.session.calls[0]
    assert "FROM canonical_observations" in sql
    assert params["metric_id"] == "vital.heart_rate"


@pytest.mark.asyncio
async def test_summarize_period_omits_metrics_with_no_window_data():
    # HR empty (1 query, no baseline) → skipped; steps has data (window+baseline).
    factory = _session_factory(
        [
            _empty(),  # vital.heart_rate window — no data
            _Row(avg_v=8200.0, min_v=0, max_v=900, count_v=14),  # activity.steps window
            _Row(avg_v=7000.0, min_v=0, max_v=1200, count_v=400),  # activity.steps baseline
        ]
    )

    summary = await DataAggregator(factory).summarize_period(
        "daily", 1, metrics=["vital.heart_rate", "activity.steps"]
    )

    assert "vital.heart_rate" not in summary.metrics
    steps = summary.metrics["activity.steps"]
    assert steps["sample_count"] == 14
    assert steps["delta_pct_vs_baseline"] == pytest.approx(17.142, rel=1e-3)


@pytest.mark.asyncio
async def test_summarize_period_handles_missing_baseline():
    window = _Row(avg_v=70.0, min_v=58, max_v=110, count_v=24)
    baseline = _empty()  # fresh install — no baseline window
    factory = _session_factory([window, baseline])

    summary = await DataAggregator(factory).summarize_period(
        "daily", 1, metrics=["vital.heart_rate"]
    )

    hr = summary.metrics["vital.heart_rate"]
    assert hr["avg"] == 70.0
    assert hr["baseline_avg"] is None
    assert hr["delta_pct_vs_baseline"] is None


@pytest.mark.asyncio
async def test_summarize_period_returns_empty_when_no_metric_has_data():
    factory = _session_factory([_empty(), _empty()])

    summary = await DataAggregator(factory).summarize_period(
        "daily", 1, metrics=["vital.heart_rate", "activity.steps"]
    )

    assert summary.metrics == {}
    assert summary.period == "daily"


@pytest.mark.asyncio
async def test_summarize_period_defaults_to_the_curated_metric_set():
    # No metrics arg → the default list is queried. All empty → one window
    # query per default metric (no baselines), and no metrics survive.
    factory = _session_factory([])  # every execute yields an empty row

    summary = await DataAggregator(factory).summarize_period("weekly", 7)

    assert summary.metrics == {}
    queried = {params["metric_id"] for _, params in factory.session.calls}
    assert queried == set(_DEFAULT_SUMMARY_METRICS)
    assert len(factory.session.calls) == len(_DEFAULT_SUMMARY_METRICS)
