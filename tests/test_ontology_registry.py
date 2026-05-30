"""Metric ontology registry tests."""

from __future__ import annotations

import json

from contracts.ontology import (
    ONTOLOGY_VERSION,
    all_metrics,
    export_registry,
    get_metric,
)


def test_get_metric_returns_expected_entries_and_none_on_miss() -> None:
    """Lookups should resolve known metrics and miss cleanly."""

    heart_rate = get_metric("vital.heart_rate")
    sleep_stage = get_metric("sleep.stage")
    blood_pressure = get_metric("blood_pressure")

    assert heart_rate is not None
    assert heart_rate.value_type == "quantity"
    assert heart_rate.canonical_unit == "bpm"

    assert sleep_stage is not None
    assert sleep_stage.value_type == "categorical"
    assert [code.code for code in sleep_stage.allowed_codes] == ["awake", "rem", "core", "deep"]

    assert blood_pressure is not None
    assert blood_pressure.value_type == "components"
    assert [component.metric_id for component in blood_pressure.components] == [
        "blood_pressure.systolic",
        "blood_pressure.diastolic",
    ]

    assert get_metric("does.not.exist") is None


def test_all_metrics_returns_registry_contents() -> None:
    """The registry should expose a stable list view for callers."""

    metrics = all_metrics()
    metric_ids = {metric.id for metric in metrics}

    assert ONTOLOGY_VERSION == "2026.05.0"
    assert len(metrics) >= 18
    assert "vital.heart_rate" in metric_ids
    assert "sleep.stage" in metric_ids
    assert "blood_pressure" in metric_ids


def test_registry_entries_match_value_type_constraints() -> None:
    """Each metric definition should be internally consistent for its value shape."""

    for metric in all_metrics():
        if metric.value_type == "quantity":
            assert metric.canonical_unit is not None
            assert metric.allowed_codes == []
            assert metric.components == []
        elif metric.value_type == "categorical":
            assert metric.canonical_unit is None
            assert metric.allowed_codes
            assert metric.components == []
        elif metric.value_type == "components":
            assert metric.canonical_unit is None
            assert metric.allowed_codes == []
            assert metric.components
        elif metric.value_type == "event":
            assert metric.canonical_unit is None
            assert metric.allowed_codes == []
        else:
            raise AssertionError(f"unexpected registry metric type in test: {metric.value_type}")


def test_export_registry_is_plain_json_serializable() -> None:
    """Frontend/plugin consumers should receive plain JSON-safe data."""

    exported = export_registry()
    encoded = json.dumps(exported)

    assert exported["ontology_version"] == ONTOLOGY_VERSION
    assert "metrics" in exported
    assert "vital.heart_rate" in exported["metrics"]
    assert '"sleep.stage"' in encoded
