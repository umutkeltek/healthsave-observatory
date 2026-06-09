# Home Assistant

HealthSave Observatory can route your canonical health data into Home Assistant so your wearables become first-class entities — usable in dashboards, templates, and (carefully) room automations. There are two supported paths.

1. **HealthSave MQTT bridge (recommended).** The bridge reads TimescaleDB and publishes retained Home Assistant MQTT discovery + state topics. This keeps Home Assistant out of the database and works even when Grafana is deployed separately.
2. **Direct SQL package (legacy / example).** Home Assistant queries TimescaleDB directly using `integrations/home-assistant/healthsave-package.yaml`. Useful for learning the schema, but MQTT is cleaner because Home Assistant never needs database credentials.

## How the HealthSave MQTT bridge publishes

The bridge publishes in two layers each cycle.

### Aggregate parent device

One device, one state topic, the legacy shape:

- Retained state topic: `healthsave/sensor/state`
- Discovery topics: `homeassistant/sensor/healthsave/<metric>/config`
- Availability: `healthsave/status`

Six entities on the parent device by default:

- `sensor.healthsave_heart_rate`
- `sensor.healthsave_hrv_7d_avg`
- `sensor.healthsave_steps_today`
- `sensor.healthsave_last_sleep_hours`
- `sensor.healthsave_source_model`
- `sensor.healthsave_room_health_state`

### Per-source sub-devices

One device per distinct `source_id` seen in recent data — Apple Watch, Whoop, iPhone, etc.:

- Retained state topic: `healthsave/source/<slug>/state` (one JSON payload per source)
- Discovery topics: `homeassistant/sensor/healthsave_<slug>/<metric>/config`
- Linked to the parent via Home Assistant's `via_device`, so HA nests sub-devices under the parent.
- Metrics carried per sub-device: `heart_rate`, `hrv_latest_ms`, `steps_today`, `last_sleep_hours`. Only metrics with a recent non-null value get a discovery message, so HA never sees ghost entities.

Example — a household running both an Apple Watch and a Whoop sees:

- `sensor.healthsave_apple_watch_heart_rate`, `_hrv_latest_ms`, `_steps_today`, `_last_sleep_hours`
- `sensor.healthsave_whoop_heart_rate`, `_hrv_latest_ms`, `_last_sleep_hours` (no `_steps_today` if Whoop hasn't logged any)

Source attribution comes from `source_id` on the ingestion tables (added to `daily_activity` and `sleep_sessions` in migration 009; native to `heart_rate` / `hrv` since v1). Rows with NULL `source_id` collapse to a single `sensor.healthsave_unknown_*` sub-device so legacy data never fragments into empty entities.

Both layers share `healthsave/status`, so HA marks every sub-device offline together if the bridge stops.

## Legacy namespace migration

Fresh installs should keep the primary `HA_MQTT_STATE_TOPIC_PREFIX`, `HA_MQTT_DEVICE_IDENTIFIER`, and `HA_MQTT_DEVICE_NAME` values on `healthsave` / `HealthSave`. If an existing Home Assistant install still has dashboards or automations on an older namespace, set `HA_MQTT_LEGACY_STATE_TOPIC_PREFIX` plus the matching legacy device identifier / name. The bridge then publishes both shapes from the same service, so Home Assistant can be migrated one entity at a time.

```bash
HA_MQTT_STATE_TOPIC_PREFIX=healthsave
HA_MQTT_DEVICE_IDENTIFIER=healthsave
HA_MQTT_DEVICE_NAME=HealthSave
HA_MQTT_LEGACY_STATE_TOPIC_PREFIX=<old-prefix>
HA_MQTT_LEGACY_DEVICE_IDENTIFIER=<old-device-id>
HA_MQTT_LEGACY_DEVICE_NAME=<old-display-name>
```

## Enabling the bridge

Enable it with Docker Compose. Two patterns:

### (a) Bring your own broker

Point the bridge at an MQTT server you already run:

```bash
HA_MQTT_ENABLED=true \
HA_MQTT_BROKER=<your-mqtt-host> \
HA_MQTT_USERNAME=<optional-user> \
HA_MQTT_PASSWORD=<optional-password> \
docker compose --profile home-assistant up -d homeassistant-mqtt
```

### (b) Use the bundled broker

Add the `mosquitto` profile and the stack runs an `eclipse-mosquitto:2` container alongside the bridge. The bridge's default `HA_MQTT_BROKER=mqtt` resolves through docker DNS, and host port `1883` is published so a Home Assistant install on the same LAN can also connect by host IP. Persistence is on a docker volume so retained messages survive restarts.

```bash
HA_MQTT_ENABLED=true \
docker compose --profile mosquitto --profile home-assistant up -d
```

The bundled broker defaults to anonymous-on-LAN. To require auth, overlay a `docker-compose.override.yml` that flips `allow_anonymous false` and mounts a password file — the conf at `deploy/mosquitto/mosquitto.conf` is read-only, so the override is the right seam.

### Useful defaults

- Discovery prefix: `homeassistant`
- State prefix: `healthsave`
- Device identifier: `healthsave`
- Publish interval: `60` seconds

## Direct SQL example

For setups that prefer DB polling, the older direct-SQL example files remain available:

- `integrations/home-assistant/healthsave-package.yaml`
- `integrations/home-assistant/secrets.example.yaml`

It is still useful for learning the Timescale schema, but the HealthSave MQTT bridge is cleaner because Home Assistant does not need database credentials. A minimal manual sensor query looks like this:

```yaml
sensor:
  - platform: sql
    db_url: !secret healthsave_db_url
    queries:
      - name: HealthSave Latest Heart Rate
        query: "SELECT value FROM heart_rate ORDER BY time DESC LIMIT 1;"
        column: "value"
```

## Shareable dashboards

A polished example dashboard is included:

- `integrations/home-assistant/README.md`
- `integrations/home-assistant/nervous-system-core-package.yaml` — helper sensors and an example room-response automation
- `integrations/home-assistant/dashboards/nervous-system-core.raw-lovelace.json` — the dashboard view

The Nervous-System Core dashboard shows HRV against a 7-day baseline, a derived nervous-load signal, recovery / readiness as a room-control signal, recent sleep / resting HR / SpO2, and source attribution. It needs the HACS custom cards `button-card`, `layout-card`, `apexcharts-card`, `mini-graph-card`, and `card-mod`. Its two room-response automations ship disabled by default — edit `light.your_room_light`, review the thresholds, then enable them manually.

## Safety

These examples are for ambience and personal dashboards, not diagnosis. Keep automations reversible, keep manual controls in charge, and avoid using health signals for anything safety-critical.

See the project [`README.md`](../../README.md) for the full integration reference, and [Findings & Body Briefs](../surfaces/findings-and-body-briefs.md) for the analysis that feeds derived signals like nervous load.
