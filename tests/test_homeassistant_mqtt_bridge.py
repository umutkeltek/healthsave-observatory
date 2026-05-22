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


def test_default_sensor_specs_use_healthsave_brand() -> None:
    """P5-b rebrand pin: every default sensor advertises a 'sensor.healthsave_*'
    entity_id. Legacy users can still get the 'healthtrack_*' shape via env
    overrides; the *defaults* are 'healthsave'.
    """
    entity_ids = {spec.entity_id for spec in default_sensor_specs()}

    assert {
        "sensor.healthsave_heart_rate",
        "sensor.healthsave_hrv_7d_avg",
        "sensor.healthsave_steps_today",
        "sensor.healthsave_last_sleep_hours",
        "sensor.healthsave_source_model",
        "sensor.healthsave_room_health_state",
    }.issubset(entity_ids)


def test_discovery_messages_use_home_assistant_mqtt_discovery_shape() -> None:
    config = HomeAssistantMQTTConfig(
        discovery_prefix="homeassistant",
        state_topic_prefix="healthsave",
        device_identifier="healthsave",
        device_name="HealthSave",
    )
    spec = SensorSpec(
        key="heart_rate",
        entity_id="sensor.healthsave_heart_rate",
        name="HealthSave Heart Rate",
        unit="bpm",
        device_class=None,
        state_class="measurement",
        icon="mdi:heart-pulse",
    )

    messages = build_discovery_messages(config, [spec])

    assert messages == [
        (
            "homeassistant/sensor/healthsave/heart_rate/config",
            {
                "availability_topic": "healthsave/status",
                "device": {
                    "identifiers": ["healthsave"],
                    "manufacturer": "HealthSave",
                    "model": "HealthSave Data Hub MQTT Bridge",
                    "name": "HealthSave",
                },
                "enabled_by_default": True,
                "icon": "mdi:heart-pulse",
                "name": "HealthSave Heart Rate",
                "object_id": "healthsave_heart_rate",
                "state_class": "measurement",
                "state_topic": "healthsave/sensor/state",
                "unique_id": "healthsave_heart_rate",
                "unit_of_measurement": "bpm",
                "value_template": "{{ value_json.heart_rate }}",
            },
            True,
        )
    ]


def test_state_messages_skip_missing_values_but_include_source_and_timestamp() -> None:
    config = HomeAssistantMQTTConfig()  # use defaults — proves the rebrand
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
            "healthsave/sensor/state",
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
    config = HomeAssistantMQTTConfig()  # defaults

    assert build_availability_message(config) == ("healthsave/status", "online", True)


def test_legacy_healthtrack_brand_remains_reachable_via_env_overrides() -> None:
    """The rebrand changes only the defaults — users on the legacy HA
    setup can pin the old shape by setting HA_MQTT_STATE_TOPIC_PREFIX /
    HA_MQTT_DEVICE_IDENTIFIER / HA_MQTT_DEVICE_NAME. This test proves
    that escape hatch by constructing the config explicitly and
    asserting the legacy topics still emerge.
    """
    config = HomeAssistantMQTTConfig(
        state_topic_prefix="healthtrack",
        device_identifier="healthtrack_owl",
        device_name="HealthTrack",
    )
    spec = SensorSpec(
        key="heart_rate",
        entity_id="sensor.healthtrack_heart_rate",
        name="HealthTrack Heart Rate",
        unit="bpm",
    )

    messages = build_discovery_messages(config, [spec])
    topic, payload, _ = messages[0]
    assert topic == "homeassistant/sensor/healthtrack/heart_rate/config"
    assert payload["availability_topic"] == "healthtrack/status"
    assert payload["state_topic"] == "healthtrack/sensor/state"
    assert payload["device"]["identifiers"] == ["healthtrack_owl"]
