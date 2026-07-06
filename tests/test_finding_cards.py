"""Unit tests for the pure Finding Card builders (packet P-03).

These exercise ``analysis.statistical.finding_cards.build_card`` directly — no
DB, no engine — proving each producer type fills a
:class:`contracts.findings.FindingCard` deterministically from the math the
detectors already persist in ``structured_data``.
"""

from __future__ import annotations

from analysis.statistical.finding_cards import build_card
from contracts.findings import FINDING_CARD_SCHEMA_VERSION, FindingCard


def test_anomaly_card_carries_zscore_delta_and_confidence():
    sd = {
        "magnitude": 3.2,
        "direction": "up",
        "context": {"value": 72.0, "baseline_mean": 55.0, "baseline_stddev": 5.0},
    }
    card = build_card("anomaly", "vital.resting_heart_rate", sd, "alert")
    assert isinstance(card, FindingCard)
    assert card.schema_version == FINDING_CARD_SCHEMA_VERSION
    assert card.metric == "vital.resting_heart_rate"
    assert "resting heart rate" in card.claim and "above" in card.claim
    assert card.effect_size.kind == "z_score"
    assert card.effect_size.value == 3.2
    assert card.effect_size.label == "large"
    assert card.delta.absolute == 72.0 - 55.0
    assert card.delta.direction == "up"
    assert card.confidence == "high"  # alert → high
    assert card.coverage.is_sufficient is True
    assert card.next_question is not None


def test_anomaly_card_post_workout_suppression_becomes_confounder():
    sd = {
        "magnitude": -2.7,
        "direction": "down",
        "context": {"value": 40.0, "baseline_mean": 55.0, "downgrade_reason": "post_workout"},
    }
    card = build_card("anomaly", "vital.hrv_sdnn", sd, "info")
    assert [c.kind for c in card.confounders] == ["post_workout"]
    assert card.confounders[0].metric == "vital.hrv_sdnn"
    assert "below" in card.claim


def test_trend_card_uses_slope_effect_and_confidence_passthrough():
    sd = {
        "slope": -0.8,
        "direction": "down",
        "period_days": 30,
        "p_value": 0.004,
        "confidence": "high",
    }
    card = build_card("trend", "vital.hrv_sdnn", sd, "info")
    assert card.effect_size.kind == "slope_per_day"
    assert card.effect_size.value == -0.8
    assert card.effect_size.p_value == 0.004
    assert card.current_window.n == 30
    assert card.confidence == "high"
    assert card.limitations  # linear-fit caveat present


def test_correlation_card_testable_pair_carries_experiment_candidate():
    sd = {
        "metric_a": "activity.steps",
        "metric_b": "vital.resting_heart_rate",
        "coefficient": -0.55,
        "method": "spearman",
        "period_days": 30,
        "p_value": 0.001,
    }
    card = build_card("correlation", "activity.steps~vital.resting_heart_rate", sd, "info")
    assert card.effect_size.kind == "spearman_rho"
    assert card.effect_size.label == "moderate"
    assert "inversely" in card.claim
    ec = card.next_question.experiment_candidate
    assert ec is not None
    # Vocabulary matches /api/v2/experiments/candidates (lever = the behavior).
    assert ec.lever == "activity.steps"
    assert ec.outcome == "vital.resting_heart_rate"
    assert ec.verdict == "testable"
    assert ec.metric_a == "activity.steps" and ec.metric_b == "vital.resting_heart_rate"
    assert ec.required_days == 28
    assert card.confidence == "high"  # p < 0.01


def test_correlation_card_non_controllable_pair_has_prose_only():
    sd = {
        "metric_a": "vital.hrv_sdnn",
        "metric_b": "vital.resting_heart_rate",
        "coefficient": -0.8,
        "method": "spearman",
        "period_days": 90,
        "p_value": 0.0001,
    }
    card = build_card("correlation", "vital.hrv_sdnn~vital.resting_heart_rate", sd, "info")
    assert card.next_question.experiment_candidate is None
    assert card.next_question.prose  # rationale from the readiness classifier


def test_recovery_card_lists_missing_inputs_as_limitations():
    sd = {
        "score": 63.0,
        "method": "supplement_v1",
        "signals_available": ["hrv", "resting_heart_rate"],
        "missing_inputs": ["temperature", "sleep_efficiency"],
    }
    card = build_card("recovery_score", "recovery", sd, "info")
    assert card.claim == "Recovery score 63"
    assert card.coverage.observation_count == 2
    assert "temperature unavailable" in card.limitations
    assert "sleep_efficiency unavailable" in card.limitations


def test_summary_card_uses_delta_when_present():
    sd = {"avg": 58.0, "delta_pct_vs_baseline": -6.4, "count": 42}
    card = build_card("summary", "vital.resting_heart_rate", sd, "info")
    assert card.delta.pct == -6.4
    assert card.delta.direction == "down"
    assert card.baseline_window.label == "30-day baseline"
    assert card.coverage.observation_count == 42


def test_summary_card_falls_back_to_average_without_baseline():
    card = build_card("summary", "activity.steps", {"avg": 8200.0, "count": 7}, "info")
    assert "averaged" in card.claim
    assert card.delta is None


def test_unknown_type_returns_none():
    assert build_card("bogus", "x", {"foo": 1}, "info") is None


def test_thin_finding_returns_none_not_a_fabricated_card():
    # No magnitude → nothing honest to say → None (persists as schema_version 0).
    assert build_card("anomaly", "vital.hrv_sdnn", {}, "info") is None
    assert build_card("correlation", "a~b", {"metric_a": "x"}, "info") is None


def test_all_card_fields_json_serializable():
    sd = {
        "metric_a": "nutrition.caffeine",
        "metric_b": "vital.hrv_sdnn",
        "coefficient": 0.6,
        "period_days": 21,
        "p_value": 0.02,
    }
    card = build_card("correlation", "nutrition.caffeine~vital.hrv_sdnn", sd, "info")
    dumped = card.model_dump(mode="json")
    assert dumped["schema_version"] == FINDING_CARD_SCHEMA_VERSION
    assert dumped["next_question"]["experiment_candidate"]["lever"] == "nutrition.caffeine"
