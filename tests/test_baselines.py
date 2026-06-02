"""Rolling baseline core (`analysis.statistical.baselines`).

Pure math + an injectable fetcher seam — no database. Pins the statistics the
anomaly detector used to compute inline (sample stddev, distinct-day count) so
the dedup can't silently drift, plus the percentile curve and the degenerate
zero-variance z-score contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from analysis.statistical.baselines import (
    Baseline,
    BaselineTracker,
    _percentile,
    compute_baseline,
)

_T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _samples(values: list[float], *, same_day: bool = False) -> list[tuple[datetime, float]]:
    """Build samples one-per-day (or all on one day) from values."""
    if same_day:
        return [(_T0 + timedelta(minutes=i), v) for i, v in enumerate(values)]
    return [(_T0 + timedelta(days=i), v) for i, v in enumerate(values)]


def test_empty_samples_have_no_baseline() -> None:
    assert compute_baseline([]) is None


def test_single_sample_has_zero_stddev_and_flat_percentiles() -> None:
    baseline = compute_baseline(_samples([42.0]))
    assert baseline is not None
    assert baseline.mean == 42.0
    assert baseline.stddev == 0.0  # n<2 → 0.0, matches old inline anomaly math
    assert baseline.p10 == baseline.p50 == baseline.p90 == 42.0
    assert baseline.n == 1
    assert baseline.days == 1


def test_mean_and_sample_stddev_match_the_old_inline_math() -> None:
    # 90/100/110 repeated → mean 100, sample stddev ≈ 8.305 (n-1), as the
    # anomaly severity-tiering test relies on.
    baseline = compute_baseline(_samples([90.0, 100.0, 110.0] * 10))
    assert baseline is not None
    assert baseline.mean == pytest.approx(100.0)
    assert baseline.stddev == pytest.approx(8.305, abs=0.01)


def test_distinct_day_count_is_independent_of_observation_count() -> None:
    # 14 observations all on one calendar day → 14 obs, 1 day (the exact
    # signal the 7-distinct-day sufficiency gate keys on).
    baseline = compute_baseline(_samples([65.0] * 14, same_day=True))
    assert baseline is not None
    assert baseline.n == 14
    assert baseline.days == 1


def test_percentiles_use_linear_interpolation() -> None:
    # 0..10 inclusive: p50 is the median 5; p10/p90 interpolate to 1 and 9.
    values = [float(v) for v in range(11)]
    assert _percentile(values, 0.50) == 5.0
    assert _percentile(values, 0.10) == pytest.approx(1.0)
    assert _percentile(values, 0.90) == pytest.approx(9.0)
    baseline = compute_baseline(_samples(values))
    assert baseline is not None
    assert (baseline.p10, baseline.p50, baseline.p90) == pytest.approx((1.0, 5.0, 9.0))


def test_zscore_is_undefined_for_zero_variance() -> None:
    flat = Baseline(mean=50.0, stddev=0.0, p10=50.0, p50=50.0, p90=50.0, n=5, days=5)
    assert flat.zscore(80.0) is None  # cannot judge — never "zero deviation"


def test_zscore_matches_manual_standard_score() -> None:
    baseline = compute_baseline(_samples([90.0, 100.0, 110.0] * 10))
    assert baseline is not None
    # (130 - 100) / 8.305 ≈ 3.61 — the value the anomaly 'alert' test expects.
    assert baseline.zscore(130.0) == pytest.approx(3.61, abs=0.01)


@pytest.mark.asyncio
async def test_tracker_fetches_then_summarizes_purely() -> None:
    captured: dict[str, Any] = {}

    async def fetcher(metric: str, device_id: int, days: int):
        captured.update(metric=metric, device_id=device_id, days=days)
        return _samples([60.0, 62.0, 64.0, 66.0])

    tracker = BaselineTracker(fetcher)
    baseline = await tracker.baseline_for("heart_rate", device_id=7, days=30)

    assert captured == {"metric": "heart_rate", "device_id": 7, "days": 30}
    assert baseline is not None
    assert baseline.mean == pytest.approx(63.0)
    assert baseline.n == 4


@pytest.mark.asyncio
async def test_tracker_returns_none_on_empty_window() -> None:
    async def fetcher(metric: str, device_id: int, days: int):
        return []

    assert await BaselineTracker(fetcher).baseline_for("hrv", device_id=1) is None
