# HealthSave Observatory pack for Home Assistant

Three automation blueprints and a "Body" dashboard for Home Assistant. They use only the entities that
the HealthSave Observatory MQTT bridge publishes. Everything is plain Home Assistant: no HACS, no
custom cards, no extra integration.

| File | What it does |
|---|---|
| [`blueprints/observatory_wind_down_lighting.yaml`](blueprints/observatory_wind_down_lighting.yaml) | Dims and warms your lights in the evening when last night's sleep was shorter than you need |
| [`blueprints/observatory_recovery_aware_morning.yaml`](blueprints/observatory_recovery_aware_morning.yaml) | Sends this morning's HRV, resting heart rate and sleep in plain words at wake time, with an optional scene |
| [`blueprints/observatory_low_data_warning.yaml`](blueprints/observatory_low_data_warning.yaml) | Warns when the bridge goes offline or when no new data has reached Observatory for hours |
| [`dashboards/observatory_body.yaml`](dashboards/observatory_body.yaml) | "Body" view: today's sleep, resting heart rate and HRV, 7-day graphs, sources and data age |

## The 5-minute path

You need HealthSave Observatory running with data arriving (see the [quick start](../../../docs/quick-start.md)),
Home Assistant 2024.10 or later, and the Home Assistant Companion app on your phone for the
notifications.

1. **Turn on the MQTT bridge.** With the broker that Observatory bundles:

   ```bash
   HA_MQTT_ENABLED=true healthsave up --mqtt --home-assistant
   ```

   This prints the broker login. With a broker you already run (Mosquitto, the Home Assistant MQTT
   add-on, EMQX), use `HA_MQTT_ENABLED=true HA_MQTT_BROKER=<host> healthsave up --home-assistant` and put
   the broker login in `.env`. Details: [Home Assistant and MQTT](../../../docs/integrations/home-assistant.md).

2. **Connect Home Assistant to the broker.** Settings > Devices & services > Add integration > MQTT,
   then enter the broker address and login. Within a minute a device called **HealthSave Observatory**
   appears. Open it and check that the entity ids match the table below.

3. **Import the blueprints.** Use the links below, or go to Settings > Automations & scenes >
   Blueprints > Import blueprint and paste the GitHub URL of each file. Then press "Create automation"
   on each blueprint and fill in the inputs.

   - [Import wind-down lighting](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fumutkeltek%2Fhealthsave-observatory%2Fblob%2Fmain%2Fintegrations%2Fhome-assistant%2Fpack%2Fblueprints%2Fobservatory_wind_down_lighting.yaml)
   - [Import recovery-aware morning](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fumutkeltek%2Fhealthsave-observatory%2Fblob%2Fmain%2Fintegrations%2Fhome-assistant%2Fpack%2Fblueprints%2Fobservatory_recovery_aware_morning.yaml)
   - [Import low-data warning](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fumutkeltek%2Fhealthsave-observatory%2Fblob%2Fmain%2Fintegrations%2Fhome-assistant%2Fpack%2Fblueprints%2Fobservatory_low_data_warning.yaml)

4. **Add the dashboard.** Settings > Dashboards > Add dashboard > New dashboard from scratch. Open it,
   then Edit dashboard > three-dot menu > Raw configuration editor, and paste
   [`dashboards/observatory_body.yaml`](dashboards/observatory_body.yaml).

Start with the low-data warning. It tells you when the other two would be acting on old numbers.

## Entity ids

The bridge (`packages/py/homeassistant_mqtt/bridge.py`) announces one device, **HealthSave
Observatory**, through MQTT discovery, with entity names such as "HRV" and "Resting Heart Rate". It
does not send a `default_entity_id`, and current Home Assistant ignores the `object_id` it sends. So
Home Assistant builds each entity id from the device name plus the entity name. With the default
settings you get these:

| Entity id | Value | Used by the pack |
|---|---|---|
| `sensor.healthsave_observatory_last_sleep_hours` | Length of the most recent sleep session, in hours | Wind-down, morning, dashboard |
| `sensor.healthsave_observatory_resting_heart_rate` | Latest resting heart rate, bpm | Morning, dashboard |
| `sensor.healthsave_observatory_hrv` | Latest HRV reading, ms | Morning, dashboard |
| `sensor.healthsave_observatory_hrv_7d_avg` | Average of all HRV readings in the last 7 days, ms | Morning, dashboard |
| `sensor.healthsave_observatory_steps_synced_at` | When Observatory last processed a step sync that carried new records (timestamp) | All three blueprints, dashboard |
| `sensor.healthsave_observatory_source_model` | Up to three most recent sources, for example "Apple Watch" | Low-data warning, dashboard |
| `sensor.healthsave_observatory_sleep_duration` | Same value as last sleep, with Home Assistant's duration device class | No |
| `sensor.healthsave_observatory_sleep_efficiency` | Asleep time as a share of the last sleep session, % | No |
| `sensor.healthsave_observatory_heart_rate` | Latest heart rate, if one arrived in the last 6 hours | No |
| `sensor.healthsave_observatory_steps_today` | Steps today | No |
| `sensor.healthsave_observatory_active_calories` | Active calories of the latest day | No |
| `sensor.healthsave_observatory_blood_oxygen` | Latest blood oxygen, % | No |
| `sensor.healthsave_observatory_recovery_score` | Latest recovery score stored from a source that has one, typically a wearable's own (for example WHOOP), passed through unchanged | No |
| `sensor.healthsave_observatory_strain` | Latest strain value stored from a source that has one | No |
| `sensor.healthsave_observatory_latest_medication_status` | Status of the latest medication dose event | No |
| `sensor.healthsave_observatory_room_state` | The bridge's coarse room state: `sleep_debt`, `recovery`, `active` or `normal`, from fixed thresholds | No |

The bridge publishes recovery score and strain only when a source provides them. The pack uses
neither: it reports readings, not scores.

Each source also gets its own device, nested under HealthSave Observatory, named after the source.
For a source called "Apple Watch" the ids are `sensor.apple_watch_heart_rate`, `sensor.apple_watch_hrv`,
`sensor.apple_watch_steps_today` and `sensor.apple_watch_last_sleep_hours`. The pack does not use
them, because their names depend on your sources.

**If your ids differ.** The bridge's own sensor list and older docs name these
`sensor.observatory_<key>`. Home Assistant does not use that name, because the bridge never sends it.
Your ids also differ if you changed `HA_MQTT_DEVICE_NAME`, or if Home Assistant created the entities
under an earlier naming scheme. Check Settings > Entities, filter by "HealthSave Observatory", then
pick the right entities in each blueprint and search and replace `healthsave_observatory_` in the
dashboard.

**What the bridge does not publish.** There is no bedtime, sleep-debt or resting heart rate
baseline entity, no sleep baseline, and no attributes, so no baseline band either. The only
baseline it publishes is the 7-day HRV average. The blueprints say where they work around this.
Per-metric readiness entities exist only when you set `HA_MQTT_READINESS_ENTITIES=true`.

## How fresh is the data

- The bridge republishes every value about once a minute and forces an update each time. An
  entity's "last updated" and "last changed" times therefore show that the bridge is alive. They do
  not show how old the data is.
- When a value stops arriving (heart rate older than 6 hours, for example), the bridge leaves it out
  of the next message. Home Assistant can keep showing the last number.
- When the bridge stops, its last-will message marks every Observatory entity unavailable.

So the pack judges data age by `sensor.healthsave_observatory_steps_synced_at`, the time Observatory
last processed a step sync from your phone. If you set `HA_MQTT_READINESS_ENTITIES=true`, the
per-metric "Observed At" timestamp sensors work as freshness sensors too.

## The blueprints

### Wind-down lighting from sleep need

At your wind-down time it compares last night's sleep with the sleep you need. If last night was
short by at least your margin, it fades the lights you pick to a lower, warmer setting. Observatory
has no bedtime or sleep-debt entity, so this uses the length of the most recent sleep session against
a number you set. It skips the evening when the data is older than your limit, because "last sleep"
could then be an older night.

To compare against your own average instead of a fixed number, create a Statistics helper
(Settings > Devices & services > Helpers > Create helper > Statistics) on
`sensor.healthsave_observatory_last_sleep_hours`, with characteristic "Mean", max age 7 days and a
sampling size of at least 10080 (one week of once-a-minute updates). Pick it as the baseline sensor.

```yaml
automation:
  - alias: Wind-down lighting
    use_blueprint:
      path: umutkeltek/observatory_wind_down_lighting.yaml
      input:
        lights:
          - light.living_room
        wind_down_time: "21:30:00"
        sleep_need_hours: 7.5
        shortfall_margin_hours: 1
        sleep_sensor: sensor.healthsave_observatory_last_sleep_hours
```

### Recovery-aware morning

At wake time it sends one notification with this morning's readings and how they compare, for
example:

```text
HRV 42 ms, 13% below your 7-day average (48 ms).
Resting heart rate 58 bpm, about the same as your baseline (57 bpm).
Last sleep 6.1 h.
```

There is no score and no advice. Resting heart rate is compared only if you give it a baseline
sensor (a Statistics helper, as above, on the resting heart rate sensor), because Observatory
publishes none. If the data is older than your limit, the message adds a line saying so. You can
also pick a scene to turn on when HRV is at least a set percentage below the 7-day average.

```yaml
automation:
  - alias: Morning readings
    use_blueprint:
      path: umutkeltek/observatory_recovery_aware_morning.yaml
      input:
        notify_device: 0123456789abcdef0123456789abcdef
        wake_time: "07:00:00"
        hrv_sensor: sensor.healthsave_observatory_hrv
        hrv_baseline_sensor: sensor.healthsave_observatory_hrv_7d_avg
        rhr_sensor: sensor.healthsave_observatory_resting_heart_rate
```

`notify_device` is the device id of your phone. Pick it in the UI rather than typing it.

### Low-data warning

It warns in two cases:

1. The bridge has been offline for longer than you allow. The bridge publishes `online` and `offline`
   on its availability topic, `observatory/status` by default, and its last-will message sets
   `offline` if it dies. Home Assistant then marks every Observatory entity unavailable, which is
   what this blueprint watches. It also catches Home Assistant losing the broker.
2. The bridge is online, but `sensor.healthsave_observatory_steps_synced_at` is older than your limit:
   the phone has stopped delivering data, or Observatory has stopped processing it.

It warns once per episode, on your phone and, if you like, in Home Assistant's notifications.

```yaml
automation:
  - alias: Observatory low-data warning
    use_blueprint:
      path: umutkeltek/observatory_low_data_warning.yaml
      input:
        notify_device: 0123456789abcdef0123456789abcdef
        bridge_entity: sensor.healthsave_observatory_source_model
        offline_minutes: 15
        sync_timestamp_sensor: sensor.healthsave_observatory_steps_synced_at
        max_sync_age_hours: 12
```

## The dashboard

One "Body" view in three sections:

- **Today:** last sleep, resting heart rate, HRV and the 7-day HRV average as tiles, plus one line
  that says how today's HRV compares with the 7-day average.
- **Last 7 days:** history graphs for sleep, HRV with its 7-day average as a second line, and
  resting heart rate, plus a daily low, average and high HRV chart from Home Assistant's long-term
  statistics. That chart fills in over the first days.
- **Sources and freshness:** the recent sources, the last step sync time, and a line that says how
  old the data is or that the bridge is offline.

Resting heart rate has no baseline line because Observatory publishes none.

## What this pack does not do

- No scores, no "readiness", no diagnosis and no medical advice. The messages report numbers and how
  they compare with your own averages.
- No bedtime or sleep-debt detection. Observatory does not publish either.
- Not real time. The phone's operating system decides when the HealthSave app syncs, and the bridge
  publishes about once a minute.
- Does not use the HealthSave iOS app's direct Home Assistant push (the `sensor.healthsave_*` states).
  That is a separate, smaller set of sensors.
- Writes nothing back to Observatory, Apple Health or Health Connect.
- No HACS integration, no custom cards, no add-on.
- Not for anything safety-critical, for access control or for medical decisions. Keep the automations
  reversible and keep manual control in charge.

## Checks

`tests/test_homeassistant_pack.py` parses every file in this folder and checks that each entity id
used here is one that the bridge publishes. It derives the ids from the bridge's discovery messages,
so a change to the bridge's names fails that test until this pack is updated.
