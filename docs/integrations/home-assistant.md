# Home Assistant And MQTT

HealthSave Observatory can publish canonical health signals into Home Assistant so wearable and Apple Health data can appear in dashboards and reversible automations.

Recommended route:

```text
HealthSave Observatory -> MQTT -> Home Assistant
```

Home Assistant does not need database credentials. The HealthSave bridge reads the Observatory store, publishes retained MQTT discovery/state topics, and Home Assistant creates entities from MQTT discovery.

## Supported Paths

| Path | Recommended? | Why |
|---|---|---|
| HealthSave MQTT bridge | Yes | Home Assistant only talks MQTT; no DB credentials; works with an external or bundled broker |
| Direct SQL package | Legacy/example | Useful for learning the schema, but Home Assistant needs DB access |

## Existing MQTT Broker

Use this when you already run Mosquitto, EMQX, Home Assistant's MQTT add-on, or another broker:

```bash
HA_MQTT_ENABLED=true HA_MQTT_BROKER=mqtt.home.arpa healthsave up --home-assistant
```

Set `HA_MQTT_USERNAME` and `HA_MQTT_PASSWORD` in `.env` when your broker requires credentials. Avoid putting MQTT passwords directly in shell history.

Bridge service: `homeassistant-mqtt`.

## Bundled Broker

Use this when you want HealthSave to run Mosquitto in the same Docker Compose stack:

```bash
HA_MQTT_ENABLED=true healthsave up --mqtt --home-assistant
```

This starts:

- `mqtt` - bundled Mosquitto broker, profile `mosquitto`.
- `homeassistant-mqtt` - HealthSave bridge, profile `home-assistant`.

The bundled broker publishes host port `1883` by default so a Home Assistant instance on the same LAN can connect to the host IP. The bundled broker defaults to anonymous LAN access; harden it with an override that disables anonymous access and mounts a password file. Base config: `deploy/mosquitto/mosquitto.conf`.

## Published Topics

The bridge publishes retained state and Home Assistant discovery topics.

Aggregate parent device:

- State topic: `healthsave/sensor/state`
- Discovery topics: `homeassistant/sensor/healthsave/<metric>/config`
- Availability topic: `healthsave/status`

Default parent entities:

- `sensor.healthsave_heart_rate`
- `sensor.healthsave_hrv_7d_avg`
- `sensor.healthsave_steps_today`
- `sensor.healthsave_last_sleep_hours`
- `sensor.healthsave_source_model`
- `sensor.healthsave_room_health_state`

Per-source sub-devices:

- State topic: `healthsave/source/<slug>/state`
- Discovery topics: `homeassistant/sensor/healthsave_<slug>/<metric>/config`
- Metrics: `heart_rate`, `hrv_latest_ms`, `steps_today`, `last_sleep_hours`

Sub-devices link to the parent HealthSave device through Home Assistant `via_device`, so Apple Watch, Whoop, iPhone, and other sources can appear as separate devices under HealthSave.

## Defaults

| Setting | Default |
|---|---|
| Discovery prefix | `homeassistant` |
| State prefix | `healthsave` |
| Device identifier | `healthsave` |
| Device name | `HealthSave` |
| Publish interval | `60` seconds |

If you have an older Home Assistant setup using a previous namespace, set legacy variables so both topic shapes publish during migration:

```bash
HA_MQTT_LEGACY_STATE_TOPIC_PREFIX=old_healthsave
HA_MQTT_LEGACY_DEVICE_IDENTIFIER=old_healthsave_device
HA_MQTT_LEGACY_DEVICE_NAME=Old HealthSave
```

## Direct SQL Example

Older direct-SQL examples remain available:

- `integrations/home-assistant/healthsave-package.yaml`
- `integrations/home-assistant/secrets.example.yaml`

Minimal example:

```yaml
sensor:
  - platform: sql
    db_url: !secret healthsave_db_url
    queries:
      - name: HealthSave Latest Heart Rate
        query: "SELECT value FROM heart_rate ORDER BY time DESC LIMIT 1;"
        column: "value"
```

Use this only if you deliberately want Home Assistant to connect to TimescaleDB.

## Dashboards And Automations

Example files:

- `integrations/home-assistant/README.md`
- `integrations/home-assistant/nervous-system-core-package.yaml`
- `integrations/home-assistant/dashboards/nervous-system-core.raw-lovelace.json`

The example dashboard shows HRV against a 7-day baseline, derived recovery/readiness signals, recent sleep, resting HR, SpO2, and source attribution.

Example automations are disabled by default. Edit entity IDs such as `light.your_room_light`, review thresholds, and enable them manually.

## Safety

Use HealthSave signals for personal dashboards and reversible comfort automations only. Do not use health signals for safety-critical automation, access control, medical decisions, or anything that could harm someone if data is delayed, incomplete, or wrong.
