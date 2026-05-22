"""Home Assistant MQTT discovery + state message builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .snapshot import HealthSnapshot


@dataclass(frozen=True)
class HomeAssistantMQTTConfig:
    """Runtime config for the HA MQTT bridge.

    This is intentionally separate from Grafana. Grafana reads TimescaleDB;
    Home Assistant consumes retained MQTT entities emitted by this bridge.
    """

    broker: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    discovery_prefix: str = "homeassistant"
    # Rebranded from 'healthtrack' (the personal_stack-era prefix) to
    # 'healthsave' on the datahub side. Env vars HA_MQTT_STATE_TOPIC_PREFIX
    # / HA_MQTT_DEVICE_IDENTIFIER / HA_MQTT_DEVICE_NAME still override
    # so users on the legacy HA setup can pin the old shape.
    state_topic_prefix: str = "healthsave"
    device_identifier: str = "healthsave"
    device_name: str = "HealthSave"
    publish_interval_seconds: int = 60


@dataclass(frozen=True)
class SensorSpec:
    key: str
    entity_id: str
    name: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None

    @property
    def object_id(self) -> str:
        return self.entity_id.split(".", 1)[1]


MQTTMessage = tuple[str, dict[str, Any] | str, bool]


def default_sensor_specs() -> list[SensorSpec]:
    """Default aggregate-device sensors the bridge publishes today.

    Source-aware sub-devices (per-source HR/HRV/steps/sleep) land in
    the P5-d bridge rewrite. P5-b keeps the wire shape the same and
    only rebrands the entity_id + display-name strings from the
    personal_stack-era ``healthtrack_*`` to the datahub-canonical
    ``healthsave_*``.
    """

    return [
        SensorSpec(
            key="heart_rate",
            entity_id="sensor.healthsave_heart_rate",
            name="HealthSave Heart Rate",
            unit="bpm",
            state_class="measurement",
            icon="mdi:heart-pulse",
        ),
        SensorSpec(
            key="hrv_7d_avg",
            entity_id="sensor.healthsave_hrv_7d_avg",
            name="HealthSave HRV 7d Avg",
            unit="ms",
            state_class="measurement",
            icon="mdi:heart",
        ),
        SensorSpec(
            key="steps_today",
            entity_id="sensor.healthsave_steps_today",
            name="HealthSave Steps Today",
            state_class="total",
            icon="mdi:walk",
        ),
        SensorSpec(
            key="last_sleep_hours",
            entity_id="sensor.healthsave_last_sleep_hours",
            name="HealthSave Last Sleep Hours",
            unit="h",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        SensorSpec(
            key="source_model",
            entity_id="sensor.healthsave_source_model",
            name="HealthSave Source Model",
            icon="mdi:database-eye",
        ),
        SensorSpec(
            key="room_health_state",
            entity_id="sensor.healthsave_room_health_state",
            name="HealthSave Room State",
            icon="mdi:home-heart",
        ),
    ]


def _topic_part(value: str) -> str:
    return value.strip("/").replace("/", "_").replace(".", "_").lower()


def state_topic(config: HomeAssistantMQTTConfig, spec: SensorSpec | None = None) -> str:
    """Stable aggregate state topic consumed by the current HA dashboard."""

    return f"{config.state_topic_prefix.rstrip('/')}/sensor/state"


def availability_topic(config: HomeAssistantMQTTConfig) -> str:
    return f"{config.state_topic_prefix.rstrip('/')}/status"


def _device_payload(config: HomeAssistantMQTTConfig) -> dict[str, Any]:
    return {
        "identifiers": [config.device_identifier],
        "manufacturer": "HealthSave",
        "model": "HealthSave Data Hub MQTT Bridge",
        "name": config.device_name,
    }


def build_discovery_messages(
    config: HomeAssistantMQTTConfig,
    specs: list[SensorSpec] | None = None,
) -> list[MQTTMessage]:
    """Build retained Home Assistant MQTT discovery config payloads."""

    specs = specs or default_sensor_specs()
    messages: list[MQTTMessage] = []
    for spec in specs:
        payload: dict[str, Any] = {
            "availability_topic": availability_topic(config),
            "device": _device_payload(config),
            "enabled_by_default": True,
            "name": spec.name,
            "object_id": spec.object_id,
            "state_topic": state_topic(config, spec),
            "unique_id": f"{config.device_identifier}_{_topic_part(spec.key)}",
            "value_template": f"{{{{ value_json.{spec.key} }}}}",
        }
        if spec.unit:
            payload["unit_of_measurement"] = spec.unit
        if spec.device_class:
            payload["device_class"] = spec.device_class
        if spec.state_class:
            payload["state_class"] = spec.state_class
        if spec.icon:
            payload["icon"] = spec.icon

        topic = (
            f"{config.discovery_prefix.rstrip('/')}/sensor/"
            f"{_topic_part(config.state_topic_prefix)}/{_topic_part(spec.key)}/config"
        )
        messages.append((topic, payload, True))
    return messages


def build_state_messages(
    config: HomeAssistantMQTTConfig,
    specs: list[SensorSpec],
    snapshot: HealthSnapshot,
) -> list[MQTTMessage]:
    """Build retained JSON state payloads for non-null snapshot values."""

    payload: dict[str, Any] = {"observed_at": snapshot.collected_at.isoformat()}
    for spec in specs:
        value = getattr(snapshot, spec.key)
        if value is None:
            continue
        payload[spec.key] = value
    return [(state_topic(config), payload, True)]


def build_availability_message(config: HomeAssistantMQTTConfig) -> MQTTMessage:
    return (availability_topic(config), "online", True)
