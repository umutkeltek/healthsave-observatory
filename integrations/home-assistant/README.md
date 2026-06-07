# Home Assistant examples

This folder contains public, copyable Home Assistant examples for using
Health Data Hub metrics in dashboards and room automations.

The recommended path is MQTT:

```bash
HA_MQTT_ENABLED=true \
HA_MQTT_BROKER=<your-mqtt-host> \
HA_MQTT_USERNAME=<optional-user> \
HA_MQTT_PASSWORD=<optional-password> \
docker compose --profile home-assistant up -d homeassistant-mqtt
```

The bridge publishes retained MQTT discovery messages, so Home Assistant
creates `sensor.healthsave_*` entities automatically.

## Nervous-System Core dashboard

Files:

- `dashboards/nervous-system-core.raw-lovelace.json` - the dashboard view
- `nervous-system-core-package.yaml` - helper sensors and example room response automation

What it shows:

- HRV against a 7-day baseline
- nervous load derived from HRV suppression
- recovery/readiness as a room-control signal
- recent sleep, resting HR, SpO2, and source attribution
- a conservative room response layer where manual control wins

Included example automations:

- `Room health - Metadata sync` keeps the dashboard reason text current
- `Room response - reduce stimulation` can dim/warm the room when the derived
  room state stays overloaded
- `Room response - evening recovery after short sleep` can bias the evening
  lighting warmer after a short sleep night

The two room-response automations ship disabled by default. Edit
`light.your_room_light`, review the thresholds, then enable them manually.

Required custom cards:

- `button-card`
- `layout-card`
- `apexcharts-card`
- `mini-graph-card`
- `card-mod`

Install those through HACS before importing the dashboard.

## Install

1. Enable the MQTT bridge and confirm Home Assistant has entities like:
   - `sensor.healthsave_hrv`
   - `sensor.healthsave_hrv_7d_avg`
   - `sensor.healthsave_last_sleep_hours`
   - `sensor.healthsave_resting_heart_rate`
   - `sensor.healthsave_blood_oxygen`
   - `sensor.healthsave_source_model`
2. Copy `nervous-system-core-package.yaml` into your Home Assistant
   packages directory.
3. Include packages from `configuration.yaml` if you do not already:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Restart Home Assistant.
5. Create a new dashboard, open the raw config editor, and paste the
   contents of `dashboards/nervous-system-core.raw-lovelace.json`.
6. Edit `light.your_room_light` in the package before enabling the example
   room response automations.

## Direct SQL example

`healthsave-package.yaml` is the older direct-SQL example. It is still useful
for learning the Timescale schema, but MQTT is cleaner for Home Assistant
because HA does not need database credentials.

## Safety

These examples are for ambience and personal dashboards, not diagnosis. Keep
automations reversible, keep manual controls in charge, and avoid using health
signals for anything safety-critical.
