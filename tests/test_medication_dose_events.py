"""Medication dose event contract tests.

These pin the additive HealthSave iOS medication wire metric without changing
the existing /api/apple/batch headers or quantity metric behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID, Provenance
from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig, sensor_specs_for_config
from normalization.apple import normalize_apple_batch
from storage.timescale.measurements import _ingest_metric


class _InsertResult:
    def one(self):
        return (True,)


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _InsertResult()


def test_medication_dose_event_normalizes_to_canonical_event() -> None:
    result = normalize_apple_batch(
        {
            "metric": "medication_dose_event",
            "samples": [
                {
                    "date": "2026-06-12T09:05:00Z",
                    "scheduled_date": "2026-06-12T09:00:00Z",
                    "status": "not_interacted",
                    "medication_name": "Vitamin D, 3",
                    "medication_metric": "medication_vitamin_d_3",
                    "medication_concept_id": "concept-123",
                    "scheduled_dose_quantity": 1,
                    "dose_quantity": 0,
                    "unit": "tablet",
                    "source": "Health",
                }
            ],
        },
        source_id=UUID("a9b1e7e0-0000-4000-8000-000000000001"),
        provenance=Provenance(
            source_plugin_id="apple-health-healthsave",
            sdk_version="test",
            captured_at=datetime.now(UTC),
        ),
        owner_id=DEFAULT_OWNER_ID,
    )

    assert result.rejected == 0
    assert result.accepted == 1
    observation = result.observations[0]
    assert observation.metric_id == "medication.dose_event"
    assert observation.value.type == "event"
    assert observation.value.status == "in_progress"
    assert observation.value.summary["status"] == "not_interacted"
    assert observation.value.summary["medication_name"] == "Vitamin D, 3"
    assert observation.value.summary["scheduled_date"] == "2026-06-12T09:00:00Z"


@pytest.mark.asyncio
async def test_medication_dose_event_ingest_writes_dedicated_rows() -> None:
    session = _FakeSession()

    result = await _ingest_metric(
        session,
        7,
        "medication_dose_event",
        [
            {
                "date": "2026-06-12T09:05:00Z",
                "scheduled_date": "2026-06-12T09:00:00Z",
                "status": "not_interacted",
                "medication_name": "Vitamin D, 3",
                "medication_metric": "medication_vitamin_d_3",
                "medication_concept_id": "concept-123",
                "scheduled_dose_quantity": 1,
                "dose_quantity": 0,
                "unit": "tablet",
                "source": "Health",
            }
        ],
    )

    assert result.accepted == 1
    assert result.rejected == 0
    sql, params = session.calls[-1]
    assert "INSERT INTO medication_dose_events" in sql
    assert params["status"] == "not_interacted"
    assert params["medication_name"] == "Vitamin D, 3"
    assert params["medication_metric"] == "medication_vitamin_d_3"


def test_homeassistant_config_has_medication_status_sensor_shape() -> None:
    specs = sensor_specs_for_config(
        HomeAssistantMQTTConfig(device_identifier="healthsave", device_name="HealthSave")
    )
    by_key = {spec.key: spec for spec in specs}

    assert (
        by_key["latest_medication_status"].entity_id
        == "sensor.healthsave_latest_medication_status"
    )
    assert by_key["latest_medication_status"].state_class == ""
    assert by_key["latest_medication_status"].icon == "mdi:pill"
