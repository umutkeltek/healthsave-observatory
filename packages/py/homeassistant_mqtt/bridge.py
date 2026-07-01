"""Home Assistant MQTT discovery + state message builders.

Two device layers ship side-by-side:

  * **Aggregate parent device** (``device_identifier`` from config, default
    ``"healthsave"``). Emits the legacy 6-sensor enum so existing HA
    dashboards keep working. Topics: ``<prefix>/sensor/state`` for
    state, ``<prefix>/status`` for availability, discovery under
    ``homeassistant/sensor/<prefix>/<metric>/config``.

  * **Per-source sub-devices** (one per distinct ``source_id`` seen in
    the recent data window). Identifier ``<device_identifier>_<slug>``,
    linked to the parent via Home Assistant's ``via_device`` so they
    show up nested under the parent in the HA device tree. Topics:
    ``<prefix>/source/<slug>/state`` for state, discovery under
    ``homeassistant/sensor/<prefix>_<slug>/<metric>/config``.

The two layers share the same availability topic so HA marks every
sub-device offline together if the bridge goes down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .snapshot import HealthSnapshot, SourceHealthSnapshot


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
    # Rebranded from the legacy 'healthtrack' prefix to 'healthsave' on
    # the datahub side. Env vars HA_MQTT_STATE_TOPIC_PREFIX
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
    component: str = "sensor"
    value_template: str | None = None

    @property
    def object_id(self) -> str:
        return self.entity_id.split(".", 1)[1]


MQTTMessage = tuple[str, dict[str, Any] | str, bool]


def default_sensor_specs() -> list[SensorSpec]:
    """Default aggregate-device sensors the bridge publishes today.

    Source-aware sub-devices (per-source HR/HRV/steps/sleep) land in
    the P5-d bridge rewrite. P5-b keeps the wire shape the same and
    only rebrands the entity_id + display-name strings from legacy
    ``healthtrack_*`` to the datahub-canonical ``healthsave_*``.
    """

    return _sensor_specs(entity_prefix="healthsave", display_name="HealthSave")


def sensor_specs_for_config(config: HomeAssistantMQTTConfig) -> list[SensorSpec]:
    """Aggregate-device sensors for the configured Home Assistant shape.

    The MQTT topic prefix, Home Assistant object ids, and display names
    should move together. That keeps the default HealthSave device clean
    while still letting legacy deployments publish ``healthtrack_*``
    entities until their dashboards are migrated.
    """

    specs = _sensor_specs(
        entity_prefix=_topic_part(config.state_topic_prefix),
        display_name=config.device_name,
    )
    if _topic_part(config.state_topic_prefix) == "healthtrack":
        specs.extend(_legacy_healthtrack_specs(config.device_name))
    return specs


def _sensor_specs(entity_prefix: str, display_name: str) -> list[SensorSpec]:
    prefix = _topic_part(entity_prefix)
    name = display_name.strip() or "HealthSave"
    return [
        SensorSpec(
            key="heart_rate",
            entity_id=f"sensor.{prefix}_heart_rate",
            name=f"{name} Heart Rate",
            unit="bpm",
            state_class="measurement",
            icon="mdi:heart-pulse",
        ),
        SensorSpec(
            key="hrv_7d_avg",
            entity_id=f"sensor.{prefix}_hrv_7d_avg",
            name=f"{name} HRV 7d Avg",
            unit="ms",
            state_class="measurement",
            icon="mdi:heart",
        ),
        SensorSpec(
            key="steps_today",
            entity_id=f"sensor.{prefix}_steps_today",
            name=f"{name} Steps Today",
            state_class="total",
            icon="mdi:walk",
        ),
        SensorSpec(
            key="steps_today_synced_at",
            entity_id=f"sensor.{prefix}_steps_today_synced_at",
            name=f"{name} Steps Synced At",
            device_class="timestamp",
            icon="mdi:clock-check",
        ),
        SensorSpec(
            key="last_sleep_hours",
            entity_id=f"sensor.{prefix}_last_sleep_hours",
            name=f"{name} Last Sleep Hours",
            unit="h",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        # Rich metrics — already populated in HealthSnapshot, now advertised on the
        # primary device so the Home Assistant adaptive-automation "brain" can read
        # fresh healthsave_* entities instead of the orphaned legacy healthtrack_*.
        SensorSpec(
            key="hrv",
            entity_id=f"sensor.{prefix}_hrv",
            name=f"{name} HRV",
            unit="ms",
            state_class="measurement",
            icon="mdi:heart-flash",
        ),
        SensorSpec(
            key="resting_heart_rate",
            entity_id=f"sensor.{prefix}_resting_heart_rate",
            name=f"{name} Resting Heart Rate",
            unit="bpm",
            state_class="measurement",
            icon="mdi:heart-pulse",
        ),
        SensorSpec(
            key="sleep_duration",
            entity_id=f"sensor.{prefix}_sleep_duration",
            name=f"{name} Sleep Duration",
            unit="h",
            device_class="duration",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        SensorSpec(
            key="sleep_efficiency",
            entity_id=f"sensor.{prefix}_sleep_efficiency",
            name=f"{name} Sleep Efficiency",
            unit="%",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        SensorSpec(
            key="strain",
            entity_id=f"sensor.{prefix}_strain",
            name=f"{name} Strain",
            state_class="measurement",
            icon="mdi:arm-flex",
        ),
        SensorSpec(
            key="recovery_score",
            entity_id=f"sensor.{prefix}_recovery_score",
            name=f"{name} Recovery Score",
            unit="%",
            state_class="measurement",
            icon="mdi:medal",
        ),
        SensorSpec(
            key="latest_medication_status",
            entity_id=f"sensor.{prefix}_latest_medication_status",
            name=f"{name} Latest Medication Status",
            state_class="",
            icon="mdi:pill",
        ),
        SensorSpec(
            key="blood_oxygen",
            entity_id=f"sensor.{prefix}_blood_oxygen",
            name=f"{name} Blood Oxygen",
            unit="%",
            state_class="measurement",
            icon="mdi:water-percent",
        ),
        SensorSpec(
            key="active_calories",
            entity_id=f"sensor.{prefix}_active_calories",
            name=f"{name} Active Calories",
            unit="kcal",
            state_class="total",
            icon="mdi:fire",
        ),
        SensorSpec(
            key="source_model",
            entity_id=f"sensor.{prefix}_source_model",
            name=f"{name} Source Model",
            icon="mdi:database-eye",
        ),
        SensorSpec(
            key="room_health_state",
            entity_id=f"sensor.{prefix}_room_health_state",
            name=f"{name} Room State",
            icon="mdi:home-heart",
        ),
    ]


def _legacy_healthtrack_specs(display_name: str) -> list[SensorSpec]:
    name = display_name.strip() or "HealthTrack"
    return [
        SensorSpec(
            key="hrv",
            entity_id="sensor.healthtrack_hrv",
            name=f"{name} HRV",
            unit="ms",
            state_class="measurement",
            icon="mdi:heart-flash",
        ),
        SensorSpec(
            key="steps",
            entity_id="sensor.healthtrack_steps",
            name=f"{name} Steps",
            unit="steps",
            state_class="total",
            icon="mdi:shoe-print",
        ),
        SensorSpec(
            key="active_calories",
            entity_id="sensor.healthtrack_active_calories",
            name=f"{name} Active Calories",
            unit="kcal",
            state_class="total",
            icon="mdi:fire",
        ),
        SensorSpec(
            key="blood_oxygen",
            entity_id="sensor.healthtrack_blood_oxygen",
            name=f"{name} Blood Oxygen",
            unit="%",
            state_class="measurement",
            icon="mdi:water-percent",
        ),
        SensorSpec(
            key="recovery_score",
            entity_id="sensor.healthtrack_recovery_score",
            name=f"{name} Recovery Score",
            unit="%",
            state_class="measurement",
            icon="mdi:medal",
        ),
        SensorSpec(
            key="sleep_duration",
            entity_id="sensor.healthtrack_sleep_duration",
            name=f"{name} Sleep Duration",
            unit="h",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        SensorSpec(
            key="sleep_efficiency",
            entity_id="sensor.healthtrack_sleep_efficiency",
            name=f"{name} Sleep Efficiency",
            unit="%",
            state_class="measurement",
            icon="mdi:sleep",
        ),
        SensorSpec(
            key="resting_heart_rate",
            entity_id="sensor.healthtrack_resting_heart_rate",
            name=f"{name} Resting Heart Rate",
            unit="bpm",
            state_class="measurement",
            icon="mdi:heart-pulse",
        ),
        SensorSpec(
            key="strain",
            entity_id="sensor.healthtrack_strain",
            name=f"{name} Strain",
            state_class="measurement",
            icon="mdi:arm-flex",
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
        "model": "HealthSave Observatory MQTT Bridge",
        "name": config.device_name,
    }


def build_discovery_messages(
    config: HomeAssistantMQTTConfig,
    specs: list[SensorSpec] | None = None,
) -> list[MQTTMessage]:
    """Build retained Home Assistant MQTT discovery config payloads."""

    if specs is None:
        specs = default_sensor_specs()
    messages: list[MQTTMessage] = []
    for spec in specs:
        payload: dict[str, Any] = {
            "availability_topic": availability_topic(config),
            "device": _device_payload(config),
            "enabled_by_default": True,
            # Re-fire HA state events on every 60s republish (even when the value is
            # unchanged) so dependent template sensors / the room_health brain
            # re-evaluate continuously instead of freezing on a startup-time value.
            "force_update": True,
            "name": _metric_name(config, spec),
            "object_id": _topic_part(spec.key),
            "state_topic": state_topic(config, spec),
            "unique_id": f"{config.device_identifier}_{_topic_part(spec.key)}",
            "value_template": spec.value_template or f"{{{{ value_json.{spec.key} }}}}",
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
            f"{config.discovery_prefix.rstrip('/')}/{spec.component}/"
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
        payload[spec.key] = value.isoformat() if hasattr(value, "isoformat") else value
    for readiness in snapshot.metric_readiness.values():
        key = _readiness_state_prefix(readiness.metric, readiness.window_key)
        payload[f"{key}_ready"] = readiness.ready
        payload[f"{key}_status"] = readiness.status
        if readiness.freshness_seconds is not None:
            payload[f"{key}_staleness_minutes"] = readiness.freshness_seconds // 60
        if readiness.observed_at is not None:
            payload[f"{key}_observed_at"] = readiness.observed_at.isoformat()
        if readiness.receipt_at is not None:
            payload[f"{key}_receipt_at"] = readiness.receipt_at.isoformat()
        if readiness.materialized_at is not None:
            payload[f"{key}_materialized_at"] = readiness.materialized_at.isoformat()
        if readiness.reason:
            payload[f"{key}_reason"] = readiness.reason
    return [(state_topic(config), payload, True)]


def readiness_sensor_specs_for_snapshot(
    config: HomeAssistantMQTTConfig,
    snapshot: HealthSnapshot,
) -> list[SensorSpec]:
    """Discovery specs for observed metric-readiness fields."""

    prefix = _topic_part(config.state_topic_prefix)
    device_name = config.device_name.strip() or "HealthSave"
    specs: list[SensorSpec] = []
    seen: set[str] = set()
    for readiness in sorted(
        snapshot.metric_readiness.values(),
        key=lambda item: _readiness_state_prefix(item.metric, item.window_key),
    ):
        key = _readiness_state_prefix(readiness.metric, readiness.window_key)
        if key in seen:
            continue
        seen.add(key)
        title = _readiness_title(key)
        specs.extend(
            [
                SensorSpec(
                    key=f"{key}_ready",
                    entity_id=f"binary_sensor.{prefix}_{key}_ready",
                    name=f"{device_name} {title} Ready",
                    component="binary_sensor",
                    icon="mdi:database-check",
                    value_template=f"{{{{ 'ON' if value_json.{key}_ready else 'OFF' }}}}",
                ),
                SensorSpec(
                    key=f"{key}_status",
                    entity_id=f"sensor.{prefix}_{key}_status",
                    name=f"{device_name} {title} Status",
                    icon="mdi:database-clock",
                ),
                SensorSpec(
                    key=f"{key}_staleness_minutes",
                    entity_id=f"sensor.{prefix}_{key}_staleness_minutes",
                    name=f"{device_name} {title} Staleness",
                    unit="min",
                    state_class="measurement",
                    icon="mdi:timer-sand",
                ),
            ]
        )
        if readiness.observed_at is not None:
            specs.append(
                SensorSpec(
                    key=f"{key}_observed_at",
                    entity_id=f"sensor.{prefix}_{key}_observed_at",
                    name=f"{device_name} {title} Observed At",
                    device_class="timestamp",
                    icon="mdi:clock-outline",
                )
            )
        if readiness.materialized_at is not None:
            specs.append(
                SensorSpec(
                    key=f"{key}_materialized_at",
                    entity_id=f"sensor.{prefix}_{key}_materialized_at",
                    name=f"{device_name} {title} Materialized At",
                    device_class="timestamp",
                    icon="mdi:database-clock-outline",
                )
            )
    return specs


def build_readiness_discovery_messages(
    config: HomeAssistantMQTTConfig,
    snapshot: HealthSnapshot,
) -> list[MQTTMessage]:
    return build_discovery_messages(config, readiness_sensor_specs_for_snapshot(config, snapshot))


def _readiness_state_prefix(metric: str, window_key: str) -> str:
    if metric == "step_count" and window_key == "today_local":
        return "steps_today"
    if window_key == "today_local":
        return f"{_topic_part(metric)}_today"
    return _topic_part(metric)


def _readiness_title(key: str) -> str:
    return key.replace("_", " ").title()


def build_availability_message(config: HomeAssistantMQTTConfig) -> MQTTMessage:
    return (availability_topic(config), "online", True)


def build_legacy_availability_messages(config: HomeAssistantMQTTConfig) -> list[MQTTMessage]:
    if _topic_part(config.state_topic_prefix) != "healthtrack":
        return []
    return [(f"{config.state_topic_prefix.rstrip('/')}/availability", "online", True)]


# ──────────────────────────────────────────────────────────────────────
# Source-aware sub-devices (P5-d)
#
# Each distinct ``source_id`` we have recent data for becomes its own
# Home Assistant device under the parent. The metrics are derived from
# :class:`SourceHealthSnapshot` fields — extending that dataclass is
# the only thing needed to surface a new per-source metric.
# ──────────────────────────────────────────────────────────────────────


SOURCE_METRIC_SPECS: tuple[tuple[str, str, str | None, str | None, str], ...] = (
    # (snapshot_attr, name_suffix, unit, state_class, icon)
    ("heart_rate", "Heart Rate", "bpm", "measurement", "mdi:heart-pulse"),
    ("hrv_latest_ms", "HRV", "ms", "measurement", "mdi:heart"),
    ("steps_today", "Steps Today", None, "total", "mdi:walk"),
    ("last_sleep_hours", "Last Sleep Hours", "h", "measurement", "mdi:sleep"),
)


def _source_device_identifier(config: HomeAssistantMQTTConfig, slug: str) -> str:
    """The HA device identifier for a per-source sub-device.

    ``<parent_identifier>_<slug>`` — e.g. ``healthsave_apple_watch``.
    """
    return f"{config.device_identifier}_{slug}"


def source_state_topic(config: HomeAssistantMQTTConfig, slug: str) -> str:
    """Per-source retained-state topic — one JSON payload covers all
    metrics for one source.
    """
    return f"{config.state_topic_prefix.rstrip('/')}/source/{slug}/state"


def _source_device_payload(
    config: HomeAssistantMQTTConfig, source_id: str, slug: str
) -> dict[str, Any]:
    """HA device descriptor for one source sub-device.

    ``via_device`` points at the parent identifier so HA nests the sub-
    device under it in the device tree. The display ``name`` uses the
    raw ``source_id`` (e.g. ``"Apple Watch"``) so it reads cleanly in
    the HA UI even though the slug is what flows through topics.
    """
    return {
        "identifiers": [_source_device_identifier(config, slug)],
        "manufacturer": "HealthSave",
        "model": "HealthSave per-source view",
        "name": source_id or "Unknown source",
        "via_device": config.device_identifier,
    }


def build_source_discovery_messages(
    config: HomeAssistantMQTTConfig,
    snapshot: SourceHealthSnapshot,
) -> list[MQTTMessage]:
    """One retained discovery payload per metric for one source.

    Only metrics with a non-None value on ``snapshot`` get a discovery
    message — HA never sees an entity for a metric the source has no
    data for. When fresh data lands later the next publish cycle
    publishes the discovery + state together (retained, so the order
    is incidental from HA's POV).
    """
    slug = snapshot.slug
    device = _source_device_payload(config, snapshot.source_id, slug)
    state_topic_value = source_state_topic(config, slug)
    messages: list[MQTTMessage] = []

    for attr, name_suffix, unit, state_class, icon in SOURCE_METRIC_SPECS:
        if getattr(snapshot, attr) is None:
            continue
        unique_id = f"{_source_device_identifier(config, slug)}_{attr}"
        payload: dict[str, Any] = {
            "availability_topic": availability_topic(config),
            "device": device,
            "enabled_by_default": True,
            # Re-fire HA state events on every 60s republish (even when the value is
            # unchanged) so dependent template sensors / the room_health brain
            # re-evaluate continuously instead of freezing on a startup-time value.
            "force_update": True,
            "name": name_suffix,
            "object_id": attr,
            "state_topic": state_topic_value,
            "unique_id": unique_id,
            "value_template": f"{{{{ value_json.{attr} }}}}",
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if state_class:
            payload["state_class"] = state_class
        if icon:
            payload["icon"] = icon

        topic = (
            f"{config.discovery_prefix.rstrip('/')}/sensor/"
            f"{_topic_part(config.state_topic_prefix)}_{slug}/{attr}/config"
        )
        messages.append((topic, payload, True))

    return messages


def _metric_name(config: HomeAssistantMQTTConfig, spec: SensorSpec) -> str:
    name = spec.name.strip()
    prefix = config.device_name.strip()
    if prefix and name.lower().startswith(f"{prefix.lower()} "):
        return name[len(prefix) :].strip()
    return name


def build_source_state_message(
    config: HomeAssistantMQTTConfig,
    snapshot: SourceHealthSnapshot,
) -> MQTTMessage:
    """Single retained JSON payload carrying every non-None metric for
    the source. Mirrors the aggregate ``build_state_messages`` shape —
    one topic per source, value_json keys match the SourceHealthSnapshot
    field names referenced in discovery's ``value_template``.
    """
    payload: dict[str, Any] = {"observed_at": snapshot.collected_at.isoformat()}
    for attr, *_ in SOURCE_METRIC_SPECS:
        value = getattr(snapshot, attr)
        if value is None:
            continue
        payload[attr] = value
    return (source_state_topic(config, snapshot.slug), payload, True)
