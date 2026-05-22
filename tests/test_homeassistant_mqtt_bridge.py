from __future__ import annotations

from datetime import UTC, datetime

from homeassistant_mqtt.bridge import (
    HomeAssistantMQTTConfig,
    SensorSpec,
    build_availability_message,
    build_discovery_messages,
    build_source_discovery_messages,
    build_source_state_message,
    build_state_messages,
    default_sensor_specs,
    sensor_specs_for_config,
    source_state_topic,
)
from homeassistant_mqtt.snapshot import HealthSnapshot, SourceHealthSnapshot


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


# ──────────────────────────────────────────────────────────────────────
# Source-aware sub-devices (P5-d)
# ──────────────────────────────────────────────────────────────────────


def _source_snapshot(**overrides) -> SourceHealthSnapshot:
    defaults = {
        "collected_at": datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        "source_id": "Apple Watch",
        "heart_rate": 72,
        "hrv_latest_ms": 64.3,
        "steps_today": 8421,
        "last_sleep_hours": 7.5,
    }
    defaults.update(overrides)
    return SourceHealthSnapshot(**defaults)


def test_source_state_topic_is_per_slug() -> None:
    config = HomeAssistantMQTTConfig()  # state_topic_prefix=healthsave
    assert source_state_topic(config, "apple_watch") == "healthsave/source/apple_watch/state"


def test_source_discovery_messages_emit_one_per_populated_metric() -> None:
    """A snapshot with all four metrics filled in produces 4 discovery
    messages — one per metric — each with the same parent via_device
    and the same per-source state_topic.
    """
    config = HomeAssistantMQTTConfig()
    snapshot = _source_snapshot()

    messages = build_source_discovery_messages(config, snapshot)

    assert len(messages) == 4
    topics = [m[0] for m in messages]
    assert "homeassistant/sensor/healthsave_apple_watch/heart_rate/config" in topics
    assert "homeassistant/sensor/healthsave_apple_watch/hrv_latest_ms/config" in topics
    assert "homeassistant/sensor/healthsave_apple_watch/steps_today/config" in topics
    assert "homeassistant/sensor/healthsave_apple_watch/last_sleep_hours/config" in topics

    # All point at the same per-source state topic.
    for _topic, payload, _retained in messages:
        assert payload["state_topic"] == "healthsave/source/apple_watch/state"

    # Every metric is nested under the parent via via_device.
    for _topic, payload, _retained in messages:
        assert payload["device"]["via_device"] == "healthsave"
        assert payload["device"]["identifiers"] == ["healthsave_apple_watch"]
        assert payload["device"]["name"] == "Apple Watch"


def test_source_discovery_skips_metrics_with_none_values() -> None:
    """A source that's only reporting heart_rate (e.g. an iPhone) gets
    one discovery message — not 4 — so HA never sees ghost entities
    for metrics the source has no data for.
    """
    config = HomeAssistantMQTTConfig()
    snapshot = _source_snapshot(
        source_id="iPhone",
        hrv_latest_ms=None,
        steps_today=None,
        last_sleep_hours=None,
    )

    messages = build_source_discovery_messages(config, snapshot)
    assert len(messages) == 1
    topic, payload, _ = messages[0]
    assert topic == "homeassistant/sensor/healthsave_iphone/heart_rate/config"
    assert payload["unique_id"] == "healthsave_iphone_heart_rate"
    assert payload["unit_of_measurement"] == "bpm"


def test_source_state_message_carries_only_non_none_fields() -> None:
    """The per-source state JSON includes observed_at + every non-None
    metric. value_template lookups in discovery (value_json.<attr>)
    must match the keys we emit here.
    """
    config = HomeAssistantMQTTConfig()
    snapshot = _source_snapshot(steps_today=None, last_sleep_hours=None)

    topic, payload, retained = build_source_state_message(config, snapshot)
    assert topic == "healthsave/source/apple_watch/state"
    assert retained is True
    assert payload == {
        "observed_at": "2026-05-22T09:00:00+00:00",
        "heart_rate": 72,
        "hrv_latest_ms": 64.3,
    }


def test_source_discovery_uses_observed_source_id_as_display_name() -> None:
    """``source_id`` carries the human-friendly label
    ('Apple Watch', "Umut's iPhone", 'Whoop'); the slug is what flows
    through topics. The HA device 'name' uses the raw source_id so
    users see the brand-correct label in the UI.
    """
    config = HomeAssistantMQTTConfig()
    snapshot = _source_snapshot(
        source_id="Whoop", hrv_latest_ms=None, steps_today=None, last_sleep_hours=None
    )

    messages = build_source_discovery_messages(config, snapshot)
    assert len(messages) == 1
    _topic, payload, _ = messages[0]
    assert payload["device"]["name"] == "Whoop"
    # And the slug derived topic + identifier.
    assert payload["state_topic"] == "healthsave/source/whoop/state"
    assert payload["device"]["identifiers"] == ["healthsave_whoop"]


def test_source_discovery_falls_back_to_unknown_label_for_empty_source_id() -> None:
    """A NULL/empty source_id collapses to slug='unknown' (per
    source_slug semantics). The HA display name falls back to a
    sensible 'Unknown source' so the device list is not empty-string.
    """
    config = HomeAssistantMQTTConfig()
    snapshot = _source_snapshot(
        source_id="", heart_rate=70, hrv_latest_ms=None, steps_today=None, last_sleep_hours=None
    )

    messages = build_source_discovery_messages(config, snapshot)
    assert len(messages) == 1
    _topic, payload, _ = messages[0]
    assert payload["device"]["name"] == "Unknown source"
    assert payload["device"]["identifiers"] == ["healthsave_unknown"]


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
    specs = sensor_specs_for_config(config)

    assert specs[0].entity_id == "sensor.healthtrack_heart_rate"
    assert specs[0].name == "HealthTrack Heart Rate"

    messages = build_discovery_messages(config, [specs[0]])
    topic, payload, _ = messages[0]
    assert topic == "homeassistant/sensor/healthtrack/heart_rate/config"
    assert payload["availability_topic"] == "healthtrack/status"
    assert payload["state_topic"] == "healthtrack/sensor/state"
    assert payload["device"]["identifiers"] == ["healthtrack_owl"]
