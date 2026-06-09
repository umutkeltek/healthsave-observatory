# Capturing your data

HealthSave Observatory is a self-hosted private body observatory: it captures
your health data from any device, normalizes it into one canonical record you
own, and keeps the raw rows on your hardware. This page is the map of how data
gets *in*.

The capture model is deliberately **source-agnostic**. Apple Health — pushed by
the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app — is the most
polished on-ramp, but it is **not the boundary**. Direct wearable plugins, file
importers, and (planned) a generic ingest API all land in the same canonical
store, so your dashboards and automations stay stable as you add or remove
devices.

## Source status

| Source | How it connects | Status |
|---|---|---|
| **Apple Health** (Apple Watch, iPhone, and anything that writes to HealthKit) | Push, via the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app — see [Apple Health / HealthKit coverage](./apple-health.md) | **Shipped** |
| **Whoop** | Direct poll plugin (OAuth) — see [Direct plugins: Whoop & Amazfit](./plugins-whoop-amazfit.md) | **Shipped** (early; bring your own Whoop developer credentials) |
| **Amazfit / Zepp** | Direct poll plugin — see [Direct plugins: Whoop & Amazfit](./plugins-whoop-amazfit.md) | **Shipped** (early) |
| **Garmin Connect** | CLI importer — see [Importers: Garmin & Samsung](./importers-garmin-samsung.md) | **Shipped** (via importer) |
| **Samsung / Huawei Health** | CLI importer (via the Health Sync app) — see [Importers: Garmin & Samsung](./importers-garmin-samsung.md) | **Shipped** (via importer) |
| **Android Health Connect** | Native capture into the generic ingest API — see [Roadmap: Android & webhooks](./roadmap-android-webhooks.md) | **Planned** |
| **Generic webhook / native API** | Any registered source posting canonical observations (HMAC-signed) — see [Roadmap: Android & webhooks](./roadmap-android-webhooks.md) | **Planned** |
| **Oura** | Via Apple Health today; a direct connector (modelled on Whoop's) is on the roadmap | Via Apple Health today; **Planned** (direct) |

If a device writes to Apple Health, the iOS bridge forwards it automatically —
that already covers Oura, many Garmin watches, Withings, and more. If it
doesn't, you have two routes that exist today: implement the `Source` plugin
contract and poll it yourself (exactly how the Whoop and Amazfit plugins work),
or use a CLI importer for file-based exports.

## Apple is the on-ramp, not the boundary

The Observatory does not assume an iPhone. Apple Health is the easiest way in
because the iOS app makes the push automatic and rich, but every other source
resolves to the same identity model and the same canonical tables. You can run
the Observatory with no Apple device at all — for example, polling Whoop
directly over OAuth — and the dashboards, findings, and routes behave
identically.

## The Source / Device / Stream model

Every capture path resolves to the same three-part identity so that downstream
consumers (dashboards, Home Assistant entities, the private API) stay stable as
hardware comes and goes:

- **Source** — the integration that brought the data in (Apple Health, Whoop,
  the Garmin importer, a registered webhook).
- **Device** — the physical emitter that produced the reading (an Apple Watch,
  a Whoop strap, an Amazfit band).
- **Stream** — the join of a source, a device, and a metric over time — the
  stable thing a panel or automation subscribes to.

This separation is why adding a second wearable does not fragment your history,
and why a disagreement between two devices (your Apple Watch vs. your Whoop on
last night's sleep) shows up as a *disagreement* rather than a fake single
truth. For the full model, see
[Source / Device / Stream](../concepts/source-device-stream.md).

## Where data lands

Whatever the source, normalized rows route through the same ingest path into
per-metric TimescaleDB tables (`heart_rate`, `hrv`, `blood_oxygen`,
`daily_activity`, `sleep_sessions`, `workouts`, and the `quantity_samples`
catch-all). Ingestion is idempotent, so you can safely re-sync or re-import
without inflating your data.

## Next steps

- [Apple Health / HealthKit coverage](./apple-health.md) — what the iOS app syncs.
- [Direct plugins: Whoop & Amazfit](./plugins-whoop-amazfit.md) — poll a wearable cloud directly.
- [Importers: Garmin & Samsung](./importers-garmin-samsung.md) — sideload file exports.
- [Roadmap: Android & webhooks](./roadmap-android-webhooks.md) — planned universal ingest.
- [Quick start](../quick-start.md) — bring the stack up.
- Root [`README.md`](../../README.md) and [`API.md`](../../API.md) — overview and the wire contract.
