# The HealthSave bridge

A one-page tour of how Apple Health data ends up in your own TimescaleDB, your own Grafana dashboards, and (if you want it) your own Home Assistant automations — with HealthSave on iOS doing the part Apple makes hard.

For the full reference and step-by-step setup, see [README.md](README.md) and [API.md](API.md). This page is the linkable summary you can hand to someone who just wants to know *what this is* before they read 500 lines.

## The pipeline, in one line

> Apple Health on your iPhone  →  **HealthSave iOS 1.5** (HealthKit bridge)  →  `POST /api/apple/batch`  →  **health-data-hub** (this repo: FastAPI + TimescaleDB)  →  **Grafana** dashboards  +  optional **Home Assistant** package  +  optional local **Ollama** AI briefing.

```
iPhone / Apple Watch        HealthSave iOS          health-data-hub               Grafana
   HealthKit store      →   HealthKit bridge   →    FastAPI + TimescaleDB    →    dashboards
                            (paid, App Store)       (this repo, ELv2, self-hosted) Home Assistant
                                                                                   Ollama briefing
```

## Who this is for

- **Quantified-self / self-hosted folks** who already run Docker on a NAS, mini PC, or homelab and want their Apple Watch data out of Apple's silo and into SQL they can query.
- **Home Assistant users** who want HR, HRV, sleep, or activity as entities for automations ("dim lights when sleep detected", "notify on 3-day resting-HR rise").
- **Grafana people** who want long-term, queryable health time series without paying a SaaS.
- **Developers** who want a clean ingest contract to build other clients/backends against — the iOS app is just one client; the API is the spec.

Not for: people who only want Apple's stock charts (Apple Health already does that better than we ever will), and not for anyone expecting medical advice (the briefing engine is informational, not diagnostic).

## What's local vs self-hosted

This is the bit Reddit/HA people ask about first, so it gets its own section.

| Piece | Where it runs | Required? | Cost |
|---|---|---|---|
| Apple Health database | On your iPhone, encrypted | yes | already there |
| HealthSave iOS 1.5 — Dashboard, Trends, on-device Export (CSV/JSON/PDF) | Your iPhone, on-device | yes if you want the bridge | free download, one-time **Pro** unlock for server sync + Home Assistant + extended history |
| **health-data-hub** (this repo) | Your own hardware: laptop, NUC, Mac mini, Synology, NAS, homelab box | **optional** | free to self-host, ELv2 source-available, runs in Docker |
| TimescaleDB + Grafana | Inside the same Docker compose stack | bundled with the hub | free |
| Ollama AI briefing | Same machine, local LLM | optional, opt-in during `./setup.sh` | free, RAM-dependent |
| Home Assistant integration | Your existing HA instance | optional | free |

**Important:** the iOS app stands on its own. Dashboard, trends, CSV/JSON/PDF export, and on-device sharing all work without ever installing this backend. The hub is for the use case "I want long-term history, my own dashboards, automations, or a local AI briefing." Don't install it because the README is interesting; install it because you have a homelab and you want this data in it.

## Setup caveats

Things people actually trip on. Worth reading before `./setup.sh`.

- **Docker is required.** On Windows, run `setup.sh` inside WSL2; it's a bash script. macOS and Linux are fine natively.
- **Free RAM caps the AI tier.** Briefing uses a local Ollama model. `setup.sh` reads your RAM + GPU and recommends a model size (see the [Hardware recommendations table](README.md#hardware-recommendations)). With < 6 GB free, skip AI; ingest still runs.
- **HTTPS is your job.** The stack defaults to plain HTTP on a LAN. For real-world use put it behind Caddy/Traefik/Cloudflared — there's a [recipe in the README](README.md#https--reverse-proxy).
- **HealthSave iOS needs the LAN-reachable URL.** First-time setup: open HealthSave → Settings → Server Sync, paste `http://your-server-ip:8000`, optionally paste your `API_KEY`. iOS won't sync to `localhost` from the phone.
- **Background sync is a Pro feature** in the iOS app. Manual sync ("Sync New Data") works without Pro for testing; ongoing background uploads need the one-time Pro unlock.
- **The first briefing can be terse.** The analysis engine needs ~24 h of heart-rate data to compute anything useful. Day 2 is usually the first real briefing.
- **Migrations are manual on existing installs.** Fresh installs auto-load `db/schema.sql`. If you're upgrading, apply the files in `db/migrations/` in order ([README → Updating Existing Installs](README.md#updating-existing-installs)).
- **The API contract is load-bearing.** `/api/apple/status` returns top-level metric objects, *not* a wrapped `{"status":"ok","counts":...}` shape. The iOS app parses it directly. If you build a compatible backend, match the shape in [API.md](API.md) or the app will break.

## What's in the box

- Long-term storage for 120+ HealthKit metrics in TimescaleDB hypertables
- Six auto-provisioned Grafana dashboards: HealthSave Overview, Activity & Movement, Heart, Sleep, Insights, and Workouts
- An optional two-brain AI briefing: a deterministic statistical engine flags interesting signals, a local LLM turns them into a short morning narrative
- A working Home Assistant example package in `integrations/home-assistant/` (SQL sensors + automations)
- Garmin Connect and Samsung/Huawei Health Sync importers in `scripts/import_garmin.py` and `scripts/import_samsung.py`
- A pluggable storage backend interface — implement the `IngestStorage` protocol if you'd rather store in InfluxDB, ClickHouse, DuckDB, or MQTT only. The first community implementation, [health-data-to-mqtt](https://github.com/bietiekay/health-data-to-mqtt), already does this.

## Links

- **GitHub (this repo):** https://github.com/umutkeltek/health-data-hub
- **HealthSave on the App Store:** https://apps.apple.com/app/id6759843047
- **API contract:** [API.md](API.md)
- **README (full reference + troubleshooting):** [README.md](README.md)

## What this isn't

- Not a cloud service. There is no umutkeltek-hosted server. You run it on your own hardware or you don't run it.
- Not a subscription. The iOS app has a one-time Pro unlock; the backend is MIT.
- Not a replacement for Apple Health. It's a place to *export to* and *build on top of*.
- Not a medical device. The briefing engine is informational; no diagnostic claims are made anywhere in this stack.
