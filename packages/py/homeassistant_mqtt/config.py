"""Environment config for the Home Assistant MQTT bridge."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .bridge import HomeAssistantMQTTConfig


@dataclass(frozen=True)
class HomeAssistantMQTTBridgeConfig:
    enabled: bool
    mqtt: HomeAssistantMQTTConfig


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


def load_config_from_env() -> HomeAssistantMQTTBridgeConfig:
    """Load non-secret bridge config from env; keep secrets in env only."""

    mqtt = HomeAssistantMQTTConfig(
        broker=os.getenv("HA_MQTT_BROKER", "localhost"),
        port=_env_int("HA_MQTT_PORT", 1883),
        username=os.getenv("HA_MQTT_USERNAME", ""),
        password=os.getenv("HA_MQTT_PASSWORD", ""),
        discovery_prefix=os.getenv("HA_MQTT_DISCOVERY_PREFIX", "homeassistant"),
        state_topic_prefix=os.getenv("HA_MQTT_STATE_TOPIC_PREFIX", "healthtrack"),
        device_identifier=os.getenv("HA_MQTT_DEVICE_IDENTIFIER", "healthtrack_owl"),
        device_name=os.getenv("HA_MQTT_DEVICE_NAME", "HealthTrack"),
        publish_interval_seconds=_env_int("HA_MQTT_PUBLISH_INTERVAL_SECONDS", 60),
    )
    return HomeAssistantMQTTBridgeConfig(
        enabled=_env_bool("HA_MQTT_ENABLED", False),
        mqtt=mqtt,
    )
