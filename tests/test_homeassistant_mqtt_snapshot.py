from __future__ import annotations

from datetime import UTC, datetime

from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig, build_state_messages, sensor_specs_for_config
from homeassistant_mqtt.snapshot import HealthSnapshot, derive_room_health_state, latest_non_null


def test_latest_non_null_uses_first_non_null_row_value() -> None:
    assert latest_non_null([(None,), (72,), (70,)], default=0) == 72


def test_bridge_exposes_steps_synced_at_timestamp_sensor() -> None:
    specs = sensor_specs_for_config(HomeAssistantMQTTConfig())
    by_key = {spec.key: spec for spec in specs}

    spec = by_key["steps_today_synced_at"]

    assert spec.entity_id == "sensor.healthsave_steps_today_synced_at"
    assert spec.device_class == "timestamp"


def test_bridge_state_payload_includes_steps_synced_at_iso_timestamp() -> None:
    synced_at = datetime(2026, 7, 1, 19, 18, tzinfo=UTC)
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 7, 1, 19, 20, tzinfo=UTC),
        heart_rate=None,
        hrv_7d_avg=None,
        steps_today=10_432,
        steps_today_synced_at=synced_at,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state=None,
    )

    specs = sensor_specs_for_config(HomeAssistantMQTTConfig())
    messages = build_state_messages(HomeAssistantMQTTConfig(), specs, snapshot)
    payload = messages[0][1]

    assert payload["steps_today"] == 10_432
    assert payload["steps_today_synced_at"] == "2026-07-01T19:18:00+00:00"


def test_derive_room_health_state_prefers_sleep_when_recent_sleep_low() -> None:
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        heart_rate=64,
        hrv_7d_avg=42.5,
        steps_today=1200,
        last_sleep_hours=4.5,
        source_model="Apple Watch via HealthSave",
        room_health_state=None,
    )

    assert derive_room_health_state(snapshot) == "sleep_debt"


def test_derive_room_health_state_prefers_recovery_when_hrv_low() -> None:
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        heart_rate=64,
        hrv_7d_avg=24.9,
        steps_today=1200,
        last_sleep_hours=7.5,
        source_model="Apple Watch via HealthSave",
        room_health_state=None,
    )

    assert derive_room_health_state(snapshot) == "recovery"


def test_derive_room_health_state_active_when_steps_are_high() -> None:
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        heart_rate=88,
        hrv_7d_avg=44,
        steps_today=9000,
        last_sleep_hours=7,
        source_model="Apple Watch via HealthSave",
        room_health_state=None,
    )

    assert derive_room_health_state(snapshot) == "active"


def test_derive_room_health_state_normal_as_safe_default() -> None:
    snapshot = HealthSnapshot(
        collected_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        heart_rate=68,
        hrv_7d_avg=45,
        steps_today=3000,
        last_sleep_hours=7,
        source_model="Apple Watch via HealthSave",
        room_health_state=None,
    )

    assert derive_room_health_state(snapshot) == "normal"
