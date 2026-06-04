"""Unit tests for :class:`analysis.statistical.aggregator.DataAggregator`.

Fake fetcher discipline — no live DB. The aggregator receives
``summarize_metric_window`` (one window fetch per metric, plus a baseline fetch
when the window has data), so each test queues rows in that order and asserts
the generic per-metric summary shape + delta math.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.statistical.aggregator import _DEFAULT_SUMMARY_METRICS, DataAggregator  # noqa: E402


def _row(avg_v, min_v, max_v, count_v):
    return {"avg": avg_v, "min": min_v, "max": max_v, "count": count_v}


def _empty():
    return _row(avg_v=None, min_v=None, max_v=None, count_v=0)


class _WindowSummarizer:
    def __init__(self, rows):
        self._queue = list(rows)
        self.calls: list[tuple[str, object, object]] = []

    async def __call__(self, metric_id, start, end):
        self.calls.append((metric_id, start, end))
        return self._queue.pop(0) if self._queue else _empty()


@pytest.mark.asyncio
async def test_summarize_period_uses_injected_fetcher_without_session():
    calls: list[tuple[str, object, object]] = []
    rows = {
        "vital.heart_rate": [
            {"avg": 65.0, "min": 55, "max": 120, "count": 24},
            {"avg": 62.0, "min": 50, "max": 140, "count": 720},
        ]
    }

    async def summarize_metric_window(metric_id, start, end):
        calls.append((metric_id, start, end))
        return rows[metric_id].pop(0)

    summary = await DataAggregator(summarize_metric_window).summarize_period(
        "daily", 1, metrics=["vital.heart_rate"]
    )

    hr = summary.metrics["vital.heart_rate"]
    assert hr["avg"] == 65.0
    assert hr["baseline_avg"] == 62.0
    assert hr["delta_pct_vs_baseline"] == pytest.approx(4.8387, rel=1e-3)
    assert [call[0] for call in calls] == ["vital.heart_rate", "vital.heart_rate"]


@pytest.mark.asyncio
async def test_summarize_period_computes_delta_vs_baseline():
    # One metric: window row then baseline row.
    window = _row(avg_v=65.0, min_v=55, max_v=120, count_v=24)
    baseline = _row(avg_v=62.0, min_v=50, max_v=140, count_v=720)
    summarize_metric_window = _WindowSummarizer([window, baseline])

    summary = await DataAggregator(summarize_metric_window).summarize_period(
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
    assert summarize_metric_window.calls[0][0] == "vital.heart_rate"


@pytest.mark.asyncio
async def test_summarize_period_omits_metrics_with_no_window_data():
    # HR empty (1 query, no baseline) → skipped; steps has data (window+baseline).
    summarize_metric_window = _WindowSummarizer(
        [
            _empty(),  # vital.heart_rate window — no data
            _row(avg_v=8200.0, min_v=0, max_v=900, count_v=14),  # activity.steps window
            _row(avg_v=7000.0, min_v=0, max_v=1200, count_v=400),  # activity.steps baseline
        ]
    )

    summary = await DataAggregator(summarize_metric_window).summarize_period(
        "daily", 1, metrics=["vital.heart_rate", "activity.steps"]
    )

    assert "vital.heart_rate" not in summary.metrics
    steps = summary.metrics["activity.steps"]
    assert steps["sample_count"] == 14
    assert steps["delta_pct_vs_baseline"] == pytest.approx(17.142, rel=1e-3)


@pytest.mark.asyncio
async def test_summarize_period_handles_missing_baseline():
    window = _row(avg_v=70.0, min_v=58, max_v=110, count_v=24)
    baseline = _empty()  # fresh install — no baseline window
    summarize_metric_window = _WindowSummarizer([window, baseline])

    summary = await DataAggregator(summarize_metric_window).summarize_period(
        "daily", 1, metrics=["vital.heart_rate"]
    )

    hr = summary.metrics["vital.heart_rate"]
    assert hr["avg"] == 70.0
    assert hr["baseline_avg"] is None
    assert hr["delta_pct_vs_baseline"] is None


@pytest.mark.asyncio
async def test_summarize_period_returns_empty_when_no_metric_has_data():
    summarize_metric_window = _WindowSummarizer([_empty(), _empty()])

    summary = await DataAggregator(summarize_metric_window).summarize_period(
        "daily", 1, metrics=["vital.heart_rate", "activity.steps"]
    )

    assert summary.metrics == {}
    assert summary.period == "daily"


@pytest.mark.asyncio
async def test_summarize_period_defaults_to_the_curated_metric_set():
    # No metrics arg → the default list is queried. All empty → one window
    # query per default metric (no baselines), and no metrics survive.
    summarize_metric_window = _WindowSummarizer([])  # every fetch yields an empty row

    summary = await DataAggregator(summarize_metric_window).summarize_period("weekly", 7)

    assert summary.metrics == {}
    queried = {call[0] for call in summarize_metric_window.calls}
    assert queried == set(_DEFAULT_SUMMARY_METRICS)
    assert len(summarize_metric_window.calls) == len(_DEFAULT_SUMMARY_METRICS)
