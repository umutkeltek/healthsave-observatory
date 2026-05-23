"""Environment config for the Home Assistant MQTT bridge."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .bridge import HomeAssistantMQTTConfig


@dataclass(frozen=True)
class HomeAssistantMQTTBridgeConfig:
    enabled: bool
    mqtt: HomeAssistantMQTTConfig
    legacy_mqtt: tuple[HomeAssistantMQTTConfig, ...] = ()

    @property
    def publish_configs(self) -> tuple[HomeAssistantMQTTConfig, ...]:
        return (self.mqtt, *self.legacy_mqtt)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_text(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw


def load_config_from_env() -> HomeAssistantMQTTBridgeConfig:
    """Load non-secret bridge config from env; keep secrets in env only."""

    mqtt = HomeAssistantMQTTConfig(
        broker=os.getenv("HA_MQTT_BROKER", "localhost"),
        port=_env_int("HA_MQTT_PORT", 1883),
        username=os.getenv("HA_MQTT_USERNAME", ""),
        password=os.getenv("HA_MQTT_PASSWORD", ""),
        discovery_prefix=os.getenv("HA_MQTT_DISCOVERY_PREFIX", "homeassistant"),
        state_topic_prefix=os.getenv("HA_MQTT_STATE_TOPIC_PREFIX", "healthsave"),
        device_identifier=os.getenv("HA_MQTT_DEVICE_IDENTIFIER", "healthsave"),
        device_name=os.getenv("HA_MQTT_DEVICE_NAME", "HealthSave"),
        publish_interval_seconds=_env_int("HA_MQTT_PUBLISH_INTERVAL_SECONDS", 60),
    )
    legacy_mqtt = _legacy_mqtt_configs(mqtt)
    return HomeAssistantMQTTBridgeConfig(
        enabled=_env_bool("HA_MQTT_ENABLED", False),
        mqtt=mqtt,
        legacy_mqtt=legacy_mqtt,
    )


def _legacy_mqtt_configs(
    base: HomeAssistantMQTTConfig,
) -> tuple[HomeAssistantMQTTConfig, ...]:
    legacy_prefix = os.getenv("HA_MQTT_LEGACY_STATE_TOPIC_PREFIX", "").strip()
    if not legacy_prefix:
        return ()

    primary_prefix = base.state_topic_prefix.strip("/")
    if legacy_prefix.strip("/") == primary_prefix:
        return ()

    return (
        HomeAssistantMQTTConfig(
            broker=base.broker,
            port=base.port,
            username=base.username,
            password=base.password,
            discovery_prefix=base.discovery_prefix,
            state_topic_prefix=legacy_prefix,
            device_identifier=_env_text(
                "HA_MQTT_LEGACY_DEVICE_IDENTIFIER",
                _identifier_from_prefix(legacy_prefix),
            ),
            device_name=_env_text("HA_MQTT_LEGACY_DEVICE_NAME", "Legacy Health Data"),
            publish_interval_seconds=base.publish_interval_seconds,
        ),
    )


def _identifier_from_prefix(prefix: str) -> str:
    return prefix.strip("/").replace("/", "_").replace(".", "_").lower() or "legacy_health"
