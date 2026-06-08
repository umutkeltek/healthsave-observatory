# HealthSave Observatory — the one-page tour

A short tour of what this is: a self-hosted **private body observatory**. It pulls your health
data from any device into one canonical record you own, shows you what changed against your own
baseline, explains it with evidence-linked findings, and lets you route or query it from your own
tools — with raw data that never leaves your hardware unless you choose to send it.

For the full reference and step-by-step setup, see [README.md](README.md) and [API.md](API.md).
This page is the linkable summary for someone who just wants to know *what this is* before reading
the full README.

## The pipeline, in one line

> Any device — Apple Health via **HealthSave** today; Android Health Connect + webhooks
> planned — → `POST /api/apple/batch` → **health-data-hub** (this repo: FastAPI + TimescaleDB,
> canonical observations you own) → the **Observatory** web app (primary surface) + optional
> **Grafana**, evidence-linked findings, optional **Home Assistant / MQTT** routes, and your own
> private API.

```
Capture (Apple = on-ramp, not the boundary)        Surfaces & routes
  Apple Health → HealthSave (iOS)         ─┐
  Whoop / Amazfit (plugins)                 ├─► health-data-hub ─► Observatory web app (primary)
  Garmin / Samsung (importers)              │   FastAPI +          Grafana (optional)
  Android Health Connect (planned)          │   TimescaleDB    →   findings + Body Briefs
  Generic webhook / native API (planned)   ─┘   canonical obs      Home Assistant / MQTT / export
                                                                    your private API
```

## Who this is for

- **Quantified-self / self-hosted folks** who already run Docker on a NAS, mini PC, or homelab and
  want their wearable data out of vendor silos and into one place they own and can query.
- **Home Assistant users** who want HR, HRV, sleep, or activity as entities for automations
  ("dim lights when sleep detected", "notify on a 3-day resting-HR rise").
- **Privacy-conscious people** who want long-term, owned health history — no SaaS holding custody.
- **Developers** who want a clean ingest contract and a **private API their own scripts, tools, and
  agents can build on** — the iOS app is just one client; the API is the spec.

Not for: people who only want Apple's stock charts (Apple Health already does that better than we
ever will), and not for anyone expecting medical advice (the analysis is informational, not
diagnostic).

## What's local vs self-hosted

This is the bit Reddit/HA people ask about first, so it gets its own section.

| Piece | Where it runs | Required? | Cost |
|---|---|---|---|
| Apple Health database | On your iPhone, encrypted | yes | already there |
| HealthSave (iOS) — Dashboard, Trends, on-device Export (CSV/JSON/PDF) | Your iPhone, on-device | yes if you want the bridge | free download, one-time **Pro** unlock for server sync + Home Assistant + extended history |
| **health-data-hub** (this repo — the Observatory backend) | Your own hardware: laptop, NUC, Mac mini, Synology, NAS, homelab box | **optional** | free to self-host, source-available (Elastic License 2.0), runs in Docker |
| Observatory web app + TimescaleDB (+ optional Grafana) | Inside the same Docker compose stack | bundled with the hub | free |
| Ollama AI narration | Same machine, local LLM | optional, opt-in during `./setup.sh` | free, RAM-dependent |
| Home Assistant integration | Your existing HA instance | optional | free |

**Important:** the iOS app stands on its own. Dashboard, trends, CSV/JSON/PDF export, and on-device
sharing all work without ever installing this backend. The Observatory is for the use case "I want
a longitudinal record I own, my own dashboards and findings, automations, or a local AI narration."
Don't install it because the README is interesting; install it because you have a homelab and you
want this data in it.

## Setup caveats

Things people actually trip on. Worth reading before `./setup.sh`.

- **Docker is required.** On Windows, run `setup.sh` inside WSL2; it's a bash script. macOS and
  Linux are fine natively.
- **The Observatory web app is the primary surface** and is being wired into the default deploy;
  **Grafana ships as the bundled dashboard today** as an optional power-user view.
- **Free RAM caps the AI tier.** Narration uses a local Ollama model. `setup.sh` reads your RAM +
  GPU and recommends a model size (see the [Hardware recommendations table](README.md#hardware-recommendations)).
  With < 6 GB free, skip AI; ingest still runs.
- **HTTPS is your job.** The stack defaults to plain HTTP on a LAN. For real-world use put it behind
  Caddy/Traefik/Cloudflared — there's a [recipe in the README](README.md#https--reverse-proxy).
- **HealthSave needs the LAN-reachable URL.** First-time setup: open HealthSave → Settings →
  Server Sync, paste `http://your-server-ip:8000`, optionally paste your `API_KEY`. iOS won't sync
  to `localhost` from the phone.
- **Background sync is a Pro feature** in the iOS app. Manual sync ("Sync New Data") works without
  Pro for testing; ongoing background uploads need the one-time Pro unlock.
- **The API contract is load-bearing.** `/api/apple/status` returns top-level metric objects, *not*
  a wrapped `{"status":"ok","counts":...}` shape. The iOS app parses it directly. If you build a
  compatible client/backend, match the shape in [API.md](API.md) or it will break.

## What's in the box

- Long-term storage for 120+ HealthKit metrics in TimescaleDB hypertables, as **canonical
  observations you own**, with stable **Source / Device / Stream** identity so dashboards and
  automations don't break as you add devices.
- The **Observatory** web app (insight-first; the primary surface, being wired into the default
  deploy) plus six bundled Grafana dashboards: HealthSave Overview, Activity & Movement, Heart,
  Sleep, Insights, and Workouts.
- An optional **two-brain** analysis: a deterministic statistical engine flags interesting signals,
  a local LLM turns them into a short narrative — the basis for the weekly **Body Brief** (in
  progress).
- Working Home Assistant examples in `integrations/home-assistant/`: MQTT dashboard, helper
  package, room-response automation, and the older direct-SQL package.
- Garmin Connect and Samsung/Huawei Health Sync importers in `scripts/import_garmin.py` and
  `scripts/import_samsung.py`.
- A pluggable storage backend interface — implement the `IngestStorage` protocol if you'd rather
  store in InfluxDB, ClickHouse, DuckDB, or MQTT only. The first community implementation,
  [health-data-to-mqtt](https://github.com/bietiekay/health-data-to-mqtt), already does this.
- **On the roadmap:** a private **CLI + local MCP server** so your own agents can query your body
  data; a generic ingest endpoint + **Android Health Connect**; and a thin routing layer.

## Links

- **GitHub (this repo):** https://github.com/umutkeltek/health-data-hub
- **HealthSave on the App Store:** https://apps.apple.com/app/id6759843047
- **API contract:** [API.md](API.md)
- **README (full reference + troubleshooting):** [README.md](README.md)
- **Home Assistant examples:** [integrations/home-assistant/README.md](integrations/home-assistant/README.md)

## What this isn't

- Not a cloud service. There is no umutkeltek-hosted server. You run it on your own hardware or you
  don't run it.
- Not a subscription. The iOS app has a one-time Pro unlock; the backend is source-available under
  the Elastic License 2.0.
- Not a replacement for Apple Health. It's a place to *bring your data into*, *understand it*, and
  *build on top of*.
- Not a medical device. The analysis is informational; no diagnostic claims are made anywhere in
  this stack.
