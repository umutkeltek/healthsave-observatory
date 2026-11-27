# Home Assistant Pack

The Home Assistant pack gives you something to run on top of the [MQTT bridge](home-assistant.md) in
a few minutes: three automation blueprints and a "Body" dashboard. It uses only the entities the
bridge publishes and only plain Home Assistant: no HACS, no custom cards, no extra integration.

Pack folder: [`integrations/home-assistant/pack/`](../../integrations/home-assistant/pack/README.md)

| Piece | What it does |
|---|---|
| Wind-down lighting from sleep need | Dims and warms the lights you pick in the evening when last night's sleep was shorter than you need |
| Recovery-aware morning | Sends this morning's HRV, resting heart rate and sleep in plain words at wake time, with an optional scene |
| Low-data warning | Warns when the bridge goes offline or when no new data has reached Observatory for hours |
| Body dashboard | Today's sleep, resting heart rate and HRV, 7-day graphs, sources and data age |

> **Screenshot placeholder.** A screenshot of the Body dashboard goes here. It has to be captured on
> a running Home Assistant with real Observatory data before this page is published with an image.

## Set It Up

1. Turn on the bridge: `HA_MQTT_ENABLED=true healthsave up --mqtt --home-assistant` for the bundled
   broker, or see [Home Assistant and MQTT](home-assistant.md) for a broker you already run.
2. In Home Assistant, add the MQTT integration with the broker address and login. A device called
   **HealthSave Observatory** appears.
3. Import the three blueprints with the links in the
   [pack README](../../integrations/home-assistant/pack/README.md#the-5-minute-path), then create an
   automation from each.
4. Paste [`dashboards/observatory_body.yaml`](../../integrations/home-assistant/pack/dashboards/observatory_body.yaml)
   into the raw configuration editor of a new dashboard.

You need Home Assistant 2024.10 or later, and the Home Assistant Companion app for the phone
notifications.

## Entity Ids

Home Assistant names the bridge's entities from the device name and the entity name, so with the
default settings they start with `sensor.healthsave_observatory_`. The pack relies on these:

- `sensor.healthsave_observatory_last_sleep_hours`
- `sensor.healthsave_observatory_resting_heart_rate`
- `sensor.healthsave_observatory_hrv`
- `sensor.healthsave_observatory_hrv_7d_avg`
- `sensor.healthsave_observatory_steps_synced_at`
- `sensor.healthsave_observatory_source_model`

The [pack README](../../integrations/home-assistant/pack/README.md#entity-ids) lists every entity the
bridge publishes, explains what to do if your ids differ, and lists what the bridge does not publish
(no bedtime, sleep-debt or resting heart rate baseline).

## Data Age

The bridge republishes every value about once a minute, so "last updated" in Home Assistant only
shows that the bridge is alive. The pack judges how old the data is by
`sensor.healthsave_observatory_steps_synced_at`, the time Observatory last processed a step sync.
The low-data warning uses the same sensor.

## Safety

The pack reports readings and how they compare with your own averages. It gives no scores, no
diagnosis and no medical advice. Use it for personal dashboards and reversible comfort automations
only, never for anything safety-critical.
