from __future__ import annotations

from homeassistant_mqtt.config import load_config_from_env


def test_load_config_from_env_keeps_bridge_disabled_by_default(monkeypatch) -> None:
    """Defaults rebranded in P5-b: prefix/identifier/name all start
    with ``healthsave`` so a fresh datahub deploy ships a coherent
    HA-side brand. Legacy ``healthtrack`` shape stays available via
    explicit env overrides (tested in
    ``test_load_config_from_env_reads_broker_and_discovery_values``).
    """
    for var in (
        "HA_MQTT_ENABLED",
        "HA_MQTT_STATE_TOPIC_PREFIX",
        "HA_MQTT_DEVICE_IDENTIFIER",
        "HA_MQTT_DEVICE_NAME",
    ):
        monkeypatch.delenv(var, raising=False)

    loaded = load_config_from_env()

    assert loaded.enabled is False
    assert loaded.mqtt.broker == "localhost"
    assert loaded.mqtt.state_topic_prefix == "healthsave"
    assert loaded.mqtt.device_identifier == "healthsave"
    assert loaded.mqtt.device_name == "HealthSave"


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


def test_load_config_from_env_reads_legacy_alias_values(monkeypatch) -> None:
    monkeypatch.setenv("HA_MQTT_ENABLED", "true")
    monkeypatch.setenv("HA_MQTT_BROKER", "mqtt.internal")
    monkeypatch.setenv("HA_MQTT_PORT", "1884")
    monkeypatch.setenv("HA_MQTT_USERNAME", "health")
    monkeypatch.setenv("HA_MQTT_PASSWORD", "secret")
    monkeypatch.setenv("HA_MQTT_DISCOVERY_PREFIX", "ha")
    monkeypatch.setenv("HA_MQTT_STATE_TOPIC_PREFIX", "healthsave")
    monkeypatch.setenv("HA_MQTT_DEVICE_IDENTIFIER", "healthsave")
    monkeypatch.setenv("HA_MQTT_DEVICE_NAME", "HealthSave")
    monkeypatch.setenv("HA_MQTT_LEGACY_STATE_TOPIC_PREFIX", "healthtrack")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_IDENTIFIER", "healthtrack")
    monkeypatch.setenv("HA_MQTT_LEGACY_DEVICE_NAME", "HealthTrack")

    loaded = load_config_from_env()

    assert loaded.publish_configs[0].state_topic_prefix == "healthsave"
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
