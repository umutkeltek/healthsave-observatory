# Overview — the one-page tour

**HealthSave Observatory** is a self-hosted **private body observatory**. It pulls
your health data from any device into one canonical record you own, shows you what
changed against your own baseline, explains it with evidence-linked findings, and
lets you route or query it from your own tools — with raw data that never leaves
your hardware unless you choose to send it.

It runs entirely on your hardware — a laptop, a NUC, a Mac mini, a Synology, a
homelab VM. No cloud, no subscription, no one else reading your numbers. Apple
Health is the easiest way in, but it is not the boundary.

## The pipeline, in two lanes

There are two ingest lanes, and they are deliberately separate:

- **Apple Health + file importers → `POST /api/apple/batch`** — the frozen v1
  compatibility contract the [HealthSave iOS app](connect-healthsave.md) depends
  on byte-for-byte. The Garmin and Samsung importers ride this same lane.
- **Native apps, generic sources & webhooks → `POST /api/v2/ingest/batch`** —
  planned. This is the source-agnostic lane for everything that isn't Apple-shaped
  (Android Health Connect, HMAC-signed webhooks, native API clients).

Both lanes normalize into the same place: **HealthSave Observatory** (FastAPI +
TimescaleDB, [canonical observations](concepts/canonical-observations.md) you own).

```
Capture (Apple = on-ramp, not the boundary)        Surfaces & routes
  Apple Health → HealthSave (iOS)         ─┐
  Whoop / Amazfit (plugins)                 ├─► HealthSave Observatory ─► Observatory web app (primary)
  Garmin / Samsung (importers)              │   FastAPI +          Grafana (optional)
  Android Health Connect (planned)          │   TimescaleDB    →   findings + Body Briefs
  Generic webhook / native API (planned)   ─┘   canonical obs      Home Assistant / MQTT / export
                                                                    your private API
```

## What you get

- **Universal capture.** Apple Health today via the iOS app; direct Whoop/Amazfit
  plugins and Garmin/Samsung importers land in the same record; Android Health
  Connect and generic webhooks are planned. See [Capture](capture/index.md).
- **One record you own.** Every source resolves to the same
  [Source / Device / Stream](concepts/source-device-stream.md) identity, so your
  dashboards and automations stay stable as you add devices.
- **A private Observatory.** *Today vs your personal baseline*, what changed, and
  where each number came from. The [Observatory web app](surfaces/observatory-web.md)
  is the primary surface; [Grafana](surfaces/grafana.md) ships as an optional view.
- **Evidence-linked findings.** A deterministic statistical engine computes the
  findings; a local LLM only narrates them. A daily briefing ships today; the
  weekly [Body Brief](surfaces/findings-and-body-briefs.md) is in progress.
- **Your own private API.** Query your history from your scripts and notebooks over
  a typed [v2 read API](api/v2-read-api.md) — locally, no third-party vendor.
- **Routes (optional).** [Home Assistant](integrations/home-assistant.md), MQTT,
  webhooks, exports — your data piped to your tools.
- **A trust boundary you can audit.** Default-deny
  [egress](concepts/privacy-and-egress.md): raw observations never leave your host;
  cloud AI is opt-in and carries only derived, on-device-redacted findings.

## What's local vs self-hosted

The iOS app stands on its own — on-device Dashboard, Trends, and Export to
CSV/JSON/PDF all work without ever installing this backend. The Observatory is for
the use case "I want a longitudinal record I own, my own dashboards and findings,
automations, or a local AI narration."

| Piece | Where it runs | Required? |
|---|---|---|
| Apple Health database | Your iPhone, encrypted | yes |
| HealthSave (iOS) — Dashboard, Trends, Export | Your iPhone, on-device | yes if you want the bridge |
| **HealthSave Observatory** (this backend) | Your own hardware | **optional** |
| Observatory web app + TimescaleDB (+ optional Grafana) | Same Docker stack | bundled |
| Ollama AI narration | Same machine, local LLM | optional, opt-in |
| Home Assistant integration | Your existing HA instance | optional |

## Get started

1. [Quick start](quick-start.md) — install the backend in three commands.
2. [Connect HealthSave](connect-healthsave.md) — pair the iOS app and sync.
3. [Findings & Body Briefs](surfaces/findings-and-body-briefs.md) — see your first findings.

## What this isn't

- Not a cloud service. You run it on your own hardware or you don't run it.
- Not a subscription. The iOS app has a one-time Pro unlock; the backend is
  source-available under the Elastic License 2.0.
- Not a replacement for Apple Health. It's a place to *bring your data into*,
  *understand it*, and *build on top of*.
- Not a medical device. The analysis is informational; no diagnostic claims.
