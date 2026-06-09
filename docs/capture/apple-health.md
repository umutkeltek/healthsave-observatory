# Apple Health / HealthKit coverage

Apple Health is the most polished on-ramp into HealthSave Observatory. The
[HealthSave](https://apps.apple.com/app/id6759843047) iOS app reads from
HealthKit on your device and **pushes** the data to your self-hosted server — no
account, nothing in a third-party cloud. It is the easiest way in, but not the
boundary: everything it captures lands in the same canonical record as the
direct plugins and importers.

## How it connects

HealthSave is a **push-based** source. The iOS app appends the API paths itself
to a base server URL you configure under **Settings → Server Sync**, then posts
batches to:

```
http://your-server-ip:8000/api/apple/batch
```

This `/api/apple/batch` endpoint is a **frozen v1 contract** — the shipping App
Store binary depends on it byte-for-byte, so its shape never changes. If you are
building your own client, target the same endpoint and payload shape. The full
request/response contract, including the exact `/api/apple/status` shape the iOS
app expects, is documented in [`API.md`](../../API.md).

## What gets synced

The server receives and stores **120+ HealthKit metrics**. Most route into a
dedicated per-metric table; anything without one falls into the
`quantity_samples` catch-all so no metric is ever dropped.

| Table | Data |
|-------|------|
| `heart_rate` | Continuous heart rate from Apple Watch / Whoop |
| `hrv` | Heart rate variability (SDNN) |
| `blood_oxygen` | SpO2 readings, with source labels for provider data |
| `daily_activity` | Steps, distance, calories, exercise minutes |
| `sleep_sessions` | Sleep duration, stages, respiratory rate |
| `workouts` | Workout type, duration, HR zones, source labels |
| `quantity_samples` | Catch-all for optional HealthKit metrics and provider aggregates (e.g. Whoop recovery score, resting HR, strain, and sleep aggregates) |

## Anything that writes to HealthKit comes along

Because HealthKit is itself an aggregator, the iOS bridge forwards data from any
app or device that writes to it — Oura, many Garmin watches, Withings scales,
and more — automatically, with source labels preserved. That is why the
[capture index](./index.md) lists Oura as available via Apple Health today even
though a direct connector is still planned.

Each row keeps its provenance through the
[Source / Device / Stream](../concepts/source-device-stream.md) model, so when
two devices report the same metric you can see the disagreement instead of a
collapsed single value.

## Connecting the app

1. Open HealthSave → **Settings → Server Sync**.
2. Set **Server URL** to `http://your-server-ip:8000` (the app appends the API paths).
3. (Optional) Set your API key if you configured one.
4. Tap **Sync New Data**.

Running `./setup.sh doctor` on the server prints the exact URL to paste into the
app. See [Quick start](../quick-start.md) for bringing the stack up.

## Notes

- Ingestion is idempotent — re-syncing never inflates your data.
- HealthSave also runs standalone (on-device Dashboard, Trends, and export to
  CSV / JSON / PDF). Self-hosting the Observatory is what adds the longitudinal
  record you own, the dashboard, the findings, and the private API.
