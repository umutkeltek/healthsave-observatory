from __future__ import annotations

import pytest
from homeassistant_mqtt.config import load_config_from_env


def test_load_config_from_env_keeps_bridge_disabled_by_default(monkeypatch) -> None:
    """A fresh bridge uses the Observatory namespace and a lean entity set."""
    for var in (
        "HA_MQTT_ENABLED",
        "HA_MQTT_STATE_TOPIC_PREFIX",
        "HA_MQTT_DEVICE_IDENTIFIER",
        "HA_MQTT_DEVICE_NAME",
        "HA_MQTT_READINESS_ENTITIES",
        "HA_MQTT_SOURCE_SLUGS",
        "HA_MQTT_LEGACY_STATE_TOPIC_PREFIX",
    ):
        monkeypatch.delenv(var, raising=False)

    loaded = load_config_from_env()

    assert loaded.enabled is False
    assert loaded.mqtt.broker == "localhost"
    assert loaded.mqtt.state_topic_prefix == "observatory"
    assert loaded.mqtt.device_identifier == "observatory"
    assert loaded.mqtt.device_name == "HealthSave Observatory"
    assert loaded.readiness_entities is False
    assert loaded.source_slugs is None


def test_load_config_from_env_reads_broker_and_discovery_values(monkeypatch) -> None:
    monkeypatch.setenv("HA_MQTT_ENABLED", "true")
    monkeypatch.setenv("HA_MQTT_BROKER", "mqtt.internal")
    monkeypatch.setenv("HA_MQTT_PORT", "1884")
    monkeypatch.setenv("HA_MQTT_USERNAME", "health")
    monkeypatch.setenv("HA_MQTT_PASSWORD", "secret")
    monkeypatch.setenv("HA_MQTT_DISCOVERY_PREFIX", "ha")
    monkeypatch.setenv("HA_MQTT_STATE_TOPIC_PREFIX", "healthtrack/demo")
    monkeypatch.setenv("HA_MQTT_DEVICE_IDENTIFIER", "health_data_hub_demo")
    monkeypatch.setenv("HA_MQTT_DEVICE_NAME", "Health Demo")
    monkeypatch.setenv("HA_MQTT_PUBLISH_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("HA_MQTT_READINESS_ENTITIES", "true")
    monkeypatch.setenv("HA_MQTT_SOURCE_SLUGS", "apple_watch, whoop,apple_watch")

    loaded = load_config_from_env()

    assert loaded.enabled is True
    assert loaded.mqtt.broker == "mqtt.internal"
    assert loaded.mqtt.port == 1884
    assert loaded.mqtt.username == "health"
    assert loaded.mqtt.password == "secret"
    assert loaded.mqtt.discovery_prefix == "ha"
    assert loaded.mqtt.state_topic_prefix == "healthtrack/demo"
    assert loaded.mqtt.device_identifier == "health_data_hub_demo"
    assert loaded.mqtt.device_name == "Health Demo"
    assert loaded.mqtt.publish_interval_seconds == 30
    assert loaded.readiness_entities is True
    assert loaded.source_slugs == frozenset({"apple_watch", "whoop"})


@pytest.mark.parametrize("raw", ["", " , "])
def test_empty_source_slug_allowlist_publishes_all_sources(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("HA_MQTT_SOURCE_SLUGS", raw)

    loaded = load_config_from_env()

    assert loaded.source_slugs is None


def test_load_config_from_env_reads_legacy_alias_values(monkeypatch) -> None:
    monkeypatch.setenv("HA_MQTT_ENABLED", "true")
    monkeypatch.setenv("HA_MQTT_BROKER", "mqtt.internal")
    monkeypatch.setenv("HA_MQTT_PORT", "1884")
    monkeypatch.setenv("HA_MQTT_USERNAME", "health")
    monkeypatch.setenv("HA_MQTT_PASSWORD", "secret")
    monkeypatch.setenv("HA_MQTT_DISCOVERY_PREFIX", "ha")
    monkeypatch.setenv("HA_MQTT_STATE_TOPIC_PREFIX", "observatory")
    monkeypatch.setenv("HA_MQTT_DEVICE_IDENTIFIER", "observatory")
    monkeypatch.setenv("HA_MQTT_DEVICE_NAME", "HealthSave Observatory")
    monkeypatch.setenv("HA_MQTT_LEGACY_STATE_TOPIC_PREFIX", "healthtrack")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_IDENTIFIER", "healthtrack")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_NAME", "HealthTrack")

    loaded = load_config_from_env()

    assert loaded.publish_configs[0].state_topic_prefix == "observatory"
    assert len(loaded.legacy_mqtt) == 1

    legacy = loaded.legacy_mqtt[0]
    assert legacy.broker == "mqtt.internal"
    assert legacy.port == 1884
    assert legacy.username == "health"
    assert legacy.password == "secret"
    assert legacy.discovery_prefix == "ha"
    assert legacy.state_topic_prefix == "healthtrack"
    assert legacy.device_identifier == "healthtrack"
    assert legacy.device_name == "HealthTrack"


def test_legacy_alias_uses_product_neutral_defaults(monkeypatch) -> None:
    monkeypatch.setenv("HA_MQTT_LEGACY_STATE_TOPIC_PREFIX", "old-health")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_IDENTIFIER", "")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_NAME", "")

    loaded = load_config_from_env()

    assert len(loaded.legacy_mqtt) == 1
    legacy = loaded.legacy_mqtt[0]
    assert legacy.state_topic_prefix == "old-health"
    assert legacy.device_identifier == "old-health"
    assert legacy.device_name == "Legacy Health Data"
