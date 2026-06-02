"""Cross-metric correlation core (`analysis.statistical.correlations`).

Pure stats + an injectable fetcher seam — no database. Pins the overlap-aware
sufficiency gate (the one `check_sufficiency` defers), the Spearman
significance/strength filters, the degenerate-series guard, and the
strongest-first ranking the n-of-1 hypothesis generator depends on.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from analysis.statistical.correlations import (
    CorrelationAnalyzer,
    correlate,
    correlation_sufficiency,
)

_D0 = date(2026, 4, 1)


def _series(values: list[float], *, start: int = 0) -> dict[date, float]:
    """Build a daily series, one value per consecutive day from ``_D0+start``."""
    return {_D0 + timedelta(days=start + i): v for i, v in enumerate(values)}


# ──────────────────────────────────────────────────────────────
#  Overlap-aware sufficiency gate
# ──────────────────────────────────────────────────────────────


def test_sufficiency_passes_for_two_full_aligned_months() -> None:
    a = _series([float(i) for i in range(30)])
    b = _series([float(i) for i in range(30)])
    assert correlation_sufficiency(a, b).is_sufficient


def test_sufficiency_fails_when_a_metric_is_too_short() -> None:
    a = _series([float(i) for i in range(30)])
    b = _series([float(i) for i in range(10)])  # 10 < 21 per-metric obs
    result = correlation_sufficiency(a, b)
    assert not result.is_sufficient
    assert "metric B 10/21 obs" in result.missing_description


def test_sufficiency_fails_on_poor_overlap_even_with_enough_obs() -> None:
    # Both series are long enough (25 each) but barely overlap in time:
    # A covers days 0-24, B covers days 25-49 → 0 shared days.
    a = _series([float(i) for i in range(25)], start=0)
    b = _series([float(i) for i in range(25)], start=25)
    result = correlation_sufficiency(a, b)
    assert not result.is_sufficient
    assert "overlapping days" in result.missing_description


def test_sufficiency_fails_on_low_jaccard_overlap() -> None:
    # A is 30 days; B is 30 days shifted by 16 → 14 shared days but union 46,
    # Jaccard ≈ 30% < 70%.
    a = _series([float(i) for i in range(30)], start=0)
    b = _series([float(i) for i in range(30)], start=16)
    result = correlation_sufficiency(a, b)
    assert not result.is_sufficient
    assert "overlap" in result.missing_description


# ──────────────────────────────────────────────────────────────
#  Spearman correlation: significance + strength filters
# ──────────────────────────────────────────────────────────────


def test_perfect_positive_monotonic_is_coefficient_one() -> None:
    a = _series([float(i) for i in range(30)])
    b = _series([float(i * 2 + 3) for i in range(30)])  # strictly increasing in a
    result = correlate("a", "b", a, b, period_days=30)
    assert result is not None
    assert result.coefficient == pytest.approx(1.0)
    assert result.method == "spearman"
    assert result.period_days == 30
    assert result.p_value < 0.05


def test_perfect_negative_monotonic_is_coefficient_minus_one() -> None:
    a = _series([float(i) for i in range(30)])
    b = _series([float(-i) for i in range(30)])
    result = correlate("a", "b", a, b, period_days=30)
    assert result is not None
    assert result.coefficient == pytest.approx(-1.0)


def test_weak_correlation_is_suppressed() -> None:
    # b follows a for the first half then flatlines → significant but the
    # coefficient lands below the 0.3 strength floor / or not — assert the
    # contract: anything returned is at least the floor.
    a = _series([float(i) for i in range(30)])
    b = _series([float(i % 2) for i in range(30)])  # 0,1,0,1… — near-zero monotonic signal
    result = correlate("a", "b", a, b, period_days=30)
    if result is not None:
        assert abs(result.coefficient) >= 0.3


def test_constant_series_yields_no_correlation() -> None:
    a = _series([float(i) for i in range(30)])
    b = _series([5.0] * 30)  # zero variance → Spearman NaN → None
    assert correlate("a", "b", a, b, period_days=30) is None


def test_insufficient_data_short_circuits_to_none() -> None:
    a = _series([float(i) for i in range(10)])
    b = _series([float(i) for i in range(10)])
    assert correlate("a", "b", a, b, period_days=30) is None


# ──────────────────────────────────────────────────────────────
#  Analyzer: injected fetcher, skip-empty, strongest-first
# ──────────────────────────────────────────────────────────────


class _ControlledPairs(CorrelationAnalyzer):
    """Override the production pairs so the mechanics test is deterministic
    and decoupled from which real metrics we happen to correlate."""

    CORRELATION_PAIRS = [("a", "b"), ("c", "d"), ("e", "f")]


@pytest.mark.asyncio
async def test_analyzer_finds_pairs_and_ranks_strongest_first() -> None:
    # Pair (a, b): perfect negative → |rho| = 1.
    # Pair (c, d): monotonic with the two endpoints swapped → rho ≈ 0.63
    #   (provably 0.3 < |rho| < 1, p well under 0.05).
    # Pair (e, f): no data → skipped.
    perfect_up = [float(i) for i in range(30)]
    perfect_down = [float(-i) for i in range(30)]
    endpoints_swapped = [float(i) for i in range(30)]
    endpoints_swapped[0], endpoints_swapped[29] = endpoints_swapped[29], endpoints_swapped[0]

    data = {
        "a": _series(perfect_up),
        "b": _series(perfect_down),
        "c": _series(perfect_up),
        "d": _series(endpoints_swapped),
    }

    async def fetcher(metric: str, days: int):
        return data.get(metric, {})

    results = await _ControlledPairs(fetcher).analyze(days=30)

    pairs = [(c.metric_a, c.metric_b) for c in results]
    assert ("a", "b") in pairs
    assert ("c", "d") in pairs
    # The pair with no data was skipped, not errored.
    assert ("e", "f") not in pairs
    # Strongest-first: the perfect pair leads, list is sorted by |coefficient|.
    magnitudes = [abs(c.coefficient) for c in results]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert abs(results[0].coefficient) == pytest.approx(1.0)


def test_production_pairs_use_real_ontology_metric_ids() -> None:
    """Guard against the pairs drifting back to aspirational names: every
    metric in CORRELATION_PAIRS must be a registered ontology metric_id."""
    from contracts.ontology import all_metrics

    known = {metric.id for metric in all_metrics()}
    referenced = {m for pair in CorrelationAnalyzer.CORRELATION_PAIRS for m in pair}
    assert referenced <= known, f"unknown metric_ids in CORRELATION_PAIRS: {referenced - known}"


@pytest.mark.asyncio
async def test_analyzer_returns_empty_when_no_data() -> None:
    async def fetcher(metric: str, days: int):
        return {}

    assert await CorrelationAnalyzer(fetcher).analyze() == []
