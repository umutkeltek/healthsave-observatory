"""Recovery Score (supplement §3) — the open, defensible composite.

Pure math, no DB. Pins the spec'd weighting and the transparent mapper curves so
the published formula stays inspectable and a tuning change is deliberate.
"""

from __future__ import annotations

from analysis.statistical.scoring import (
    _baseline_deviation_to_score,
    _temp_deviation_to_score,
    compute_recovery_score,
)


def test_baseline_deviation_mapper_curve() -> None:
    # Baseline → neutral 50.
    assert _baseline_deviation_to_score(0.0, higher_is_better=True) == 50.0
    # Good direction saturates to 100 at full scale, bad to 0.
    assert _baseline_deviation_to_score(20.0, higher_is_better=True) == 100.0
    assert _baseline_deviation_to_score(-20.0, higher_is_better=True) == 0.0
    # Direction flips for "lower is better" signals (RHR, resp rate).
    assert _baseline_deviation_to_score(-20.0, higher_is_better=False) == 100.0
    assert _baseline_deviation_to_score(20.0, higher_is_better=False) == 0.0
    # Clamped beyond full scale.
    assert _baseline_deviation_to_score(1000.0, higher_is_better=True) == 100.0


def test_temp_mapper_is_a_symmetric_penalty() -> None:
    assert _temp_deviation_to_score(0.0) == 100.0
    assert _temp_deviation_to_score(0.5) == 50.0
    assert _temp_deviation_to_score(-0.5) == 50.0  # fever and hypothermia both penalized
    assert _temp_deviation_to_score(1.0) == 0.0
    assert _temp_deviation_to_score(-3.0) == 0.0  # clamped


def test_perfect_recovery_is_100() -> None:
    score = compute_recovery_score(
        hrv_vs_baseline=20.0,
        rhr_vs_baseline=-20.0,
        sleep_efficiency=100.0,
        temp_deviation=0.0,
        resp_rate_vs_baseline=-20.0,
    )
    assert score == 100


def test_worst_recovery_is_0() -> None:
    score = compute_recovery_score(
        hrv_vs_baseline=-20.0,
        rhr_vs_baseline=20.0,
        sleep_efficiency=0.0,
        temp_deviation=1.0,
        resp_rate_vs_baseline=20.0,
    )
    assert score == 0


def test_neutral_baseline_score() -> None:
    # All signals at baseline, sleep 50, temp perfect:
    # 0.40*50 + 0.25*50 + 0.15*50 + 0.10*100 + 0.10*50 = 55.
    score = compute_recovery_score(
        hrv_vs_baseline=0.0,
        rhr_vs_baseline=0.0,
        sleep_efficiency=50.0,
        temp_deviation=0.0,
        resp_rate_vs_baseline=0.0,
    )
    assert score == 55


def test_result_is_always_clamped_to_0_100() -> None:
    score = compute_recovery_score(
        hrv_vs_baseline=10_000.0,
        rhr_vs_baseline=-10_000.0,
        sleep_efficiency=10_000.0,
        temp_deviation=0.0,
        resp_rate_vs_baseline=-10_000.0,
    )
    assert score == 100


def test_hrv_dominates_respiratory_rate_by_weight() -> None:
    """Same-size improvement in HRV (40%) must move the score more than in
    respiratory rate (10%) — the weighting is the whole point."""
    base = compute_recovery_score(0.0, 0.0, 50.0, 0.0, 0.0)
    hrv_bump = compute_recovery_score(10.0, 0.0, 50.0, 0.0, 0.0)
    resp_bump = compute_recovery_score(0.0, 0.0, 50.0, 0.0, -10.0)
    assert hrv_bump > resp_bump > base
