from __future__ import annotations

from homeassistant_mqtt.config import load_config_from_env


def test_load_config_from_env_keeps_bridge_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("HA_MQTT_ENABLED", raising=False)

    loaded = load_config_from_env()

    assert loaded.enabled is False
    assert loaded.mqtt.broker == "localhost"
    assert loaded.mqtt.state_topic_prefix == "healthtrack"
    assert loaded.mqtt.device_identifier == "healthtrack_owl"
    assert loaded.mqtt.device_name == "HealthTrack"


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
