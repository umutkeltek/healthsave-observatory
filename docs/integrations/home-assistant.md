# Home Assistant And MQTT

HealthSave Observatory can publish canonical health signals into Home Assistant so wearable data becomes dashboard and automation context.

The recommended path is MQTT:

```text
HealthSave Observatory -> MQTT -> Home Assistant
```

Home Assistant does not need database credentials. The bridge reads TimescaleDB, publishes retained MQTT discovery/state topics, and Home Assistant creates entities from MQTT discovery.

## Two Supported Paths

| Path | Recommended? | Why |
|---|---|---|
| HealthSave MQTT bridge | Yes | Home Assistant only talks to MQTT; no DB credentials; works with external or bundled broker |
| Direct SQL package | Legacy/example | Useful for learning schema, but Home Assistant needs DB access |

## Start With Existing MQTT Broker

Use this when you already run Mosquitto, EMQX, Home Assistant's MQTT add-on, or another broker.

```bash
HA_MQTT_ENABLED=true \
HA_MQTT_BROKER=<your-mqtt-host> \
HA_MQTT_USERNAME=<optional-user> \
HA_MQTT_PASSWORD=<optional-password> \
./healthsave up --home-assistant
```

The bridge service is `homeassistant-mqtt`.

## Start With Bundled Broker

Use this when you want HealthSave to run Mosquitto in the same Docker Compose stack:

```bash
HA_MQTT_ENABLED=true ./healthsave up --mqtt --home-assistant
```

This starts:

- `mqtt` - bundled Mosquitto broker, profile `mosquitto`
- `homeassistant-mqtt` - HealthSave bridge, profile `home-assistant`

The bundled broker publishes host port `1883` by default so a Home Assistant instance on the same LAN can connect to the host IP.

The bundled broker defaults to anonymous-on-LAN. For a hardened deployment, add an override that disables anonymous access and mounts a password file. The base config lives at `deploy/mosquitto/mosquitto.conf`.

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

Sub-devices are linked to the parent HealthSave device with Home Assistant `via_device`, so Apple Watch, Whoop, iPhone, or other sources can appear as separate devices under HealthSave.

## Defaults

| Setting | Default |
|---|---|
| Discovery prefix | `homeassistant` |
| State prefix | `healthsave` |
| Device identifier | `healthsave` |
| Device name | `HealthSave` |
| Publish interval | `60` seconds |

If you have an older Home Assistant setup using a previous namespace, set the legacy variables so both shapes publish during migration:

```bash
HA_MQTT_LEGACY_STATE_TOPIC_PREFIX=<old-prefix>
HA_MQTT_LEGACY_DEVICE_IDENTIFIER=<old-device-id>
HA_MQTT_LEGACY_DEVICE_NAME=<old-display-name>
```

## Direct SQL Example

The older direct-SQL examples remain available:

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

The example dashboard shows HRV against a 7-day baseline, nervous-load style derived signals, recovery/readiness context, recent sleep, resting HR, SpO2, and source attribution.

The example automations are disabled by default. Edit entity IDs such as `light.your_room_light`, review thresholds, and enable manually.

## Safety

Use HealthSave signals for personal dashboards and reversible comfort automations only. Do not use health signals for safety-critical automation, access control, medical decisions, or anything that could harm someone if the data is delayed, incomplete, or wrong.
