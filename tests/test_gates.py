"""Data-sufficiency gate (`analysis.statistical.gates.check_sufficiency`).

Pins the gate the anomaly detector now routes through, the observation-vs-day
shortfall accounting, the days-until-sufficient heuristic, and the deliberate
ValueErrors that stop an unmet (or unmodelled) gate from silently passing.
"""

from __future__ import annotations

import pytest
from analysis.statistical.gates import check_sufficiency
from analysis.types import DataSummary


def test_anomaly_detection_sufficient_at_threshold() -> None:
    # Exactly the 14-observation / 7-day floor → sufficient.
    result = check_sufficiency(
        "anomaly_detection", DataSummary(observation_count=14, days_with_data=7)
    )
    assert result.is_sufficient
    assert result.missing_description is None
    assert result.days_until_sufficient is None


def test_observation_shortfall_gives_no_day_estimate() -> None:
    # Days met, observations short — we can't estimate calendar days remaining
    # from an observation shortfall (per-day sampling rate is unknown).
    result = check_sufficiency(
        "anomaly_detection", DataSummary(observation_count=5, days_with_data=7)
    )
    assert not result.is_sufficient
    assert "5/14 observations" in result.missing_description
    assert "days with data" not in result.missing_description
    assert result.days_until_sufficient is None


def test_day_shortfall_estimates_days_until_sufficient() -> None:
    # Observations met, only 3 of 7 distinct days → 4 calendar days to go.
    result = check_sufficiency(
        "anomaly_detection", DataSummary(observation_count=40, days_with_data=3)
    )
    assert not result.is_sufficient
    assert "3/7 days with data" in result.missing_description
    assert result.days_until_sufficient == 4


def test_both_short_reports_both_and_uses_day_estimate() -> None:
    result = check_sufficiency(
        "anomaly_detection", DataSummary(observation_count=2, days_with_data=1)
    )
    assert not result.is_sufficient
    assert "2/14 observations" in result.missing_description
    assert "1/7 days with data" in result.missing_description
    assert result.days_until_sufficient == 6


def test_trend_analysis_uses_its_own_higher_thresholds() -> None:
    # 21 obs / 14 days for trends — 14 days is short of trend's 14? exactly meets.
    assert check_sufficiency(
        "trend_analysis", DataSummary(observation_count=21, days_with_data=14)
    ).is_sufficient
    assert not check_sufficiency(
        "trend_analysis", DataSummary(observation_count=14, days_with_data=7)
    ).is_sufficient


def test_weekly_summary_gates_on_distinct_days_only() -> None:
    # min_days_in_week=5 maps onto days_with_data; observation count is irrelevant.
    assert check_sufficiency(
        "weekly_summary", DataSummary(observation_count=0, days_with_data=5)
    ).is_sufficient
    short = check_sufficiency("weekly_summary", DataSummary(observation_count=0, days_with_data=4))
    assert not short.is_sufficient
    assert short.days_until_sufficient == 1


def test_unknown_analysis_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown analysis_type"):
        check_sufficiency("not_a_real_analysis", DataSummary())


@pytest.mark.parametrize("analysis_type", ["correlation_analysis", "recovery_score"])
def test_unmodelled_requirements_refuse_to_guess(analysis_type: str) -> None:
    # These carry cross-metric / per-session inputs a plain DataSummary can't
    # express — the gate must refuse rather than falsely report "sufficient".
    with pytest.raises(ValueError, match="specialized gate"):
        check_sufficiency(analysis_type, DataSummary(observation_count=999, days_with_data=999))
