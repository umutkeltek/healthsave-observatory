"""Period-summary → Recovery Score mapping (analysis.statistical.recovery).

Covers the honest-accounting contract: a score is produced only when a real
signal is present, the temperature source preference (wrist deviation over
absolute body temp), and the structured_data shape the v2 read API + web hero
consume (``structured_data.score``).
"""

from __future__ import annotations

from analysis.statistical.recovery import (
    BODY_TEMP_METRIC,
    HRV_METRIC,
    RESP_METRIC,
    RHR_METRIC,
    WRIST_TEMP_DEVIATION_METRIC,
    recovery_finding_data,
)


def _metric(avg=None, baseline_avg=None, delta_pct_vs_baseline=None):
    return {
        "avg": avg,
        "min": avg,
        "max": avg,
        "sample_count": 1,
        "baseline_avg": baseline_avg,
        "delta_pct_vs_baseline": delta_pct_vs_baseline,
    }


def test_no_signal_returns_none_not_a_fabricated_score() -> None:
    # Empty summary — nothing to score; must NOT invent one.
    assert recovery_finding_data({}) is None


def test_metric_present_but_no_baseline_delta_is_not_a_signal() -> None:
    # Metric appears in the window but has no baseline to compare against:
    # there is no honest deviation, so it cannot manufacture a score alone.
    summary = {HRV_METRIC: _metric(avg=55.0, baseline_avg=None, delta_pct_vs_baseline=None)}
    assert recovery_finding_data(summary) is None


def test_hrv_alone_is_suppressed_as_insufficient_evidence() -> None:
    summary = {HRV_METRIC: _metric(avg=60.0, baseline_avg=50.0, delta_pct_vs_baseline=20.0)}
    assert recovery_finding_data(summary) is None


def test_three_inputs_with_autonomic_anchor_produce_partial_score() -> None:
    summary = {
        HRV_METRIC: _metric(avg=60.0, baseline_avg=50.0, delta_pct_vs_baseline=20.0),
        RHR_METRIC: _metric(avg=48.0, baseline_avg=52.0, delta_pct_vs_baseline=-7.7),
        RESP_METRIC: _metric(avg=14.0, baseline_avg=15.0, delta_pct_vs_baseline=-6.7),
    }
    data = recovery_finding_data(summary)
    assert data is not None
    assert data["signals_available"] == ["hrv", "resting_heart_rate", "respiratory_rate"]
    assert data["input_count"] == 3
    assert data["input_total"] == 5
    assert data["available_weight"] == 0.65
    assert data["evidence_level"] == "partial"
    assert data["method"] == "supplement_v2_available_weight"
    assert data["formula_version"] == 2
    assert data["contributors"]["hrv_vs_baseline_pct"] == 20.0
    assert data["contributors"]["sleep_efficiency"] is None


def test_temperature_alone_is_suppressed_as_insufficient_evidence() -> None:
    summary = {WRIST_TEMP_DEVIATION_METRIC: _metric(avg=0.4)}
    assert recovery_finding_data(summary) is None


def test_body_temperature_alone_is_suppressed() -> None:
    summary = {BODY_TEMP_METRIC: _metric(avg=37.2, baseline_avg=36.8)}
    assert recovery_finding_data(summary) is None


def test_wrist_deviation_preferred_over_body_temperature_in_qualified_score() -> None:
    summary = {
        HRV_METRIC: _metric(avg=60.0, baseline_avg=50.0, delta_pct_vs_baseline=20.0),
        RHR_METRIC: _metric(avg=48.0, baseline_avg=52.0, delta_pct_vs_baseline=-7.7),
        RESP_METRIC: _metric(avg=14.0, baseline_avg=15.0, delta_pct_vs_baseline=-6.7),
        WRIST_TEMP_DEVIATION_METRIC: _metric(avg=0.2),
        BODY_TEMP_METRIC: _metric(avg=37.5, baseline_avg=36.8),
    }
    data = recovery_finding_data(summary)
    assert data is not None
    assert data["contributors"]["temperature_deviation_c"] == 0.2


def test_full_signal_set_scores_and_records_each_contributor() -> None:
    summary = {
        HRV_METRIC: _metric(avg=60.0, baseline_avg=50.0, delta_pct_vs_baseline=20.0),
        RHR_METRIC: _metric(avg=48.0, baseline_avg=52.0, delta_pct_vs_baseline=-7.7),
        RESP_METRIC: _metric(avg=14.0, baseline_avg=15.0, delta_pct_vs_baseline=-6.7),
        WRIST_TEMP_DEVIATION_METRIC: _metric(avg=0.0),
    }
    data = recovery_finding_data(summary)
    assert data is not None
    assert set(data["signals_available"]) == {
        "hrv",
        "resting_heart_rate",
        "respiratory_rate",
        "temperature",
    }
    # Only sleep remains missing once every wearable signal is present.
    assert data["missing_inputs"] == ["sleep_efficiency"]
    assert data["method"] == "supplement_v2_available_weight"
    assert data["formula_version"] == 2
    assert data["input_count"] == 4
    assert data["input_total"] == 5
    assert data["available_weight"] == 0.75
    assert data["evidence_level"] == "partial"
    contributors = data["contributors"]
    assert contributors["hrv_vs_baseline_pct"] == 20.0
    assert contributors["rhr_vs_baseline_pct"] == -7.7
    assert contributors["respiratory_rate_vs_baseline_pct"] == -6.7
    assert contributors["temperature_deviation_c"] == 0.0
