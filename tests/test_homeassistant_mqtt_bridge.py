from __future__ import annotations

from datetime import UTC, datetime

from homeassistant_mqtt.bridge import (
    HomeAssistantMQTTConfig,
    SensorSpec,
    build_availability_message,
    build_discovery_messages,
    build_state_messages,
    default_sensor_specs,
)
from homeassistant_mqtt.snapshot import HealthSnapshot


def test_default_sensor_specs_match_ambient_os_contract() -> None:
    entity_ids = {spec.entity_id for spec in default_sensor_specs()}

    assert {
        "sensor.healthtrack_heart_rate",
        "sensor.healthtrack_hrv_7d_avg",
        "sensor.healthtrack_steps_today",
        "sensor.healthtrack_last_sleep_hours",
        "sensor.health_source_model",
        "sensor.room_health_state",
    }.issubset(entity_ids)


def test_discovery_messages_use_home_assistant_mqtt_discovery_shape() -> None:
    config = HomeAssistantMQTTConfig(
        discovery_prefix="homeassistant",
        state_topic_prefix="healthtrack",
        device_identifier="healthtrack_owl",
        device_name="HealthTrack",
    )
    spec = SensorSpec(
        key="heart_rate",
        entity_id="sensor.healthtrack_heart_rate",
        name="HealthTrack Heart Rate",
        unit="bpm",
        device_class=None,
        state_class="measurement",
        icon="mdi:heart-pulse",
    )

    messages = build_discovery_messages(config, [spec])

    assert messages == [
        (
            "homeassistant/sensor/healthtrack/heart_rate/config",
            {
                "availability_topic": "healthtrack/status",
                "device": {
                    "identifiers": ["healthtrack_owl"],
                    "manufacturer": "HealthSave",
                    "model": "Health Data Hub MQTT Bridge",
                    "name": "HealthTrack",
                },
                "enabled_by_default": True,
                "icon": "mdi:heart-pulse",
                "name": "HealthTrack Heart Rate",
                "object_id": "healthtrack_heart_rate",
                "state_class": "measurement",
                "state_topic": "healthtrack/sensor/state",
                "unique_id": "healthtrack_owl_heart_rate",
                "unit_of_measurement": "bpm",
                "value_template": "{{ value_json.heart_rate }}",
            },
            True,
        )
    ]


def test_state_messages_skip_missing_values_but_include_source_and_timestamp() -> None:
    config = HomeAssistantMQTTConfig(state_topic_prefix="healthtrack")
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=None,
        steps_today=4123,
        last_sleep_hours=6.75,
        source_model="Apple Watch via HealthSave",
        room_health_state="recovery",
    )

    messages = build_state_messages(config, default_sensor_specs(), snapshot)

    assert messages == [
        (
            "healthtrack/sensor/state",
            {
                "heart_rate": 72,
                "last_sleep_hours": 6.75,
                "observed_at": "2026-05-12T09:30:00+00:00",
                "room_health_state": "recovery",
                "source_model": "Apple Watch via HealthSave",
                "steps_today": 4123,
            },
            True,
        )
    ]


def test_availability_message_is_retained_online_state() -> None:
    config = HomeAssistantMQTTConfig(state_topic_prefix="healthtrack")

    assert build_availability_message(config) == ("healthtrack/status", "online", True)
