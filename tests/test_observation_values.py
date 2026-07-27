"""Tagged observation value contract tests."""

from __future__ import annotations

from typing import get_args

from contracts.values import ObservationValue
from pydantic import TypeAdapter

OBSERVATION_VALUE_ADAPTER = TypeAdapter(ObservationValue)


def _round_trip(payload: dict[str, object]) -> dict[str, object]:
    """Validate a union payload and dump it back to plain Python data."""

    model = OBSERVATION_VALUE_ADAPTER.validate_python(payload)
    return OBSERVATION_VALUE_ADAPTER.dump_python(model, mode="python")


def test_observation_value_routes_quantity_payload() -> None:
    """The discriminator must route quantity payloads to the quantity model."""

    payload = {
        "type": "quantity",
        "value": 72.5,
        "unit": "bpm",
        "canonical_value": 72.5,
        "canonical_unit": "bpm",
    }

    model = OBSERVATION_VALUE_ADAPTER.validate_python(payload)

    assert model.type == "quantity"
    assert model.unit == "bpm"
    assert _round_trip(payload) == payload


def test_observation_value_round_trips_every_member() -> None:
    """Every tagged-union member should survive dict -> model -> dict intact."""

    payloads = [
        {
            "type": "quantity",
            "value": 48.2,
            "unit": "ms",
            "canonical_value": 48.2,
            "canonical_unit": "ms",
        },
        {
            "type": "categorical",
            "code": "deep",
            "label": "Deep",
            "coding": [
                {
                    "system": "internal",
                    "code": "deep",
                    "display": "Deep",
                }
            ],
        },
        {"type": "boolean", "value": True},
        {
            "type": "components",
            "components": [
                {
                    "metric_id": "blood_pressure.systolic",
                    "value": {
                        "type": "quantity",
                        "value": 120.0,
                        "unit": "mmHg",
                        "canonical_value": 120.0,
                        "canonical_unit": "mmHg",
                    },
                },
                {
                    "metric_id": "blood_pressure.diastolic",
                    "value": {
                        "type": "quantity",
                        "value": 80.0,
                        "unit": "mmHg",
                        "canonical_value": 80.0,
                        "canonical_unit": "mmHg",
                    },
                },
            ],
        },
        {
            "type": "event",
            "label": "Sleep session",
            "status": "completed",
            "summary": {"sleep_stage_count": 4},
        },
        {
            "type": "waveform",
            "blob_ref": "objects/ecg/abc123",
            "content_type": "application/octet-stream",
            "sample_rate_hz": 256.0,
            "channel_count": 1,
            "duration_ms": 30000,
            "summary": {"lead": "I"},
        },
        {
            "type": "json",
            "value": {
                "score": 87,
                "bands": ["low", "mid", "high"],
                "metadata": {"source": "computed"},
            },
        },
    ]

    for payload in payloads:
        assert _round_trip(payload) == payload


def test_observation_value_discriminator_covers_expected_tags() -> None:
    """The public union should advertise the full value-tag surface."""

    expected_types = {
        "quantity",
        "categorical",
        "boolean",
        "components",
        "event",
        "waveform",
        "json",
    }

    union_members = get_args(get_args(ObservationValue)[0])
    actual_types = {
        model_cls.model_fields["type"].annotation.__args__[0] for model_cls in union_members
    }

    assert actual_types == expected_types
