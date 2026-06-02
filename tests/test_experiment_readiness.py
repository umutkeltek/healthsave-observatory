"""Unit tests for the experiment-readiness classifier (pure, no I/O)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.statistical.experiment_readiness import (  # noqa: E402
    NOT_CONTROLLABLE,
    TESTABLE,
    classify_candidate,
)


def test_activity_vs_vital_is_testable_with_activity_as_lever():
    verdict = classify_candidate("activity.steps", "vital.resting_heart_rate")
    assert verdict.verdict == TESTABLE
    assert verdict.lever == "activity.steps"
    assert verdict.outcome == "vital.resting_heart_rate"
    assert verdict.required_days == 28
    assert "steps" in verdict.suggested_protocol
    assert "resting heart rate" in verdict.suggested_protocol


def test_lever_detection_is_order_independent():
    verdict = classify_candidate("vital.resting_heart_rate", "activity.steps")
    assert verdict.verdict == TESTABLE
    assert verdict.lever == "activity.steps"
    assert verdict.outcome == "vital.resting_heart_rate"


def test_nutrition_vs_vital_is_testable():
    verdict = classify_candidate("nutrition.caffeine", "vital.hrv_sdnn")
    assert verdict.verdict == TESTABLE
    assert verdict.lever == "nutrition.caffeine"
    assert verdict.outcome == "vital.hrv_sdnn"


def test_two_physiological_outcomes_are_not_controllable():
    verdict = classify_candidate("vital.hrv_sdnn", "vital.resting_heart_rate")
    assert verdict.verdict == NOT_CONTROLLABLE
    assert verdict.lever is None
    assert verdict.outcome is None
    assert verdict.suggested_protocol is None
    assert verdict.required_days is None
    assert "physiological" in verdict.rationale


def test_two_behaviors_are_not_controllable():
    # steps ↔ active energy are mechanically coupled — no independent outcome.
    verdict = classify_candidate("activity.steps", "activity.active_energy")
    assert verdict.verdict == NOT_CONTROLLABLE
    assert "behaviors" in verdict.rationale
