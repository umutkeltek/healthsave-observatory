# HealthSave Observatory

[![CI](https://github.com/umutkeltek/health-data-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/umutkeltek/health-data-hub/actions/workflows/ci.yml)
[![License: Elastic 2.0](https://img.shields.io/badge/License-Elastic--2.0-005571.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515.svg?logo=postgresql&logoColor=white)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20LLM-000000.svg)](https://ollama.com/)
[![Download on the App Store](https://img.shields.io/badge/Download-App%20Store-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/app/id6759843047)

> **Your whole body, in one place you own — and it actually tells you something.**
> HealthSave Observatory is a **self-hosted private body observatory**. It captures your health data from *any* device, builds a longitudinal record you own, explains what's changing with evidence-linked findings and weekly **Body Briefs**, and exposes a private API your own scripts and agents can query — with **raw data that never leaves your hardware unless you choose to send it**.

> **New here?** [BRIDGE.md](BRIDGE.md) is the one-page tour: pipeline diagram, who it's for, what's local vs self-hosted, setup gotchas. Read that first if 500 lines of README is too much.

**Keywords:** `self-hosted health dashboard` · `private health observatory` · `apple-health` · `android-health-connect` · `healthkit` · `wearables` · `whoop` · `oura` · `garmin` · `hrv` · `quantified-self` · `biohacking` · `personal-health-api` · `mcp` · `home-assistant` · `timescaledb` · `fastapi` · `local-llm` · `privacy` · `docker`

Your health data is scattered across silos you don't control — Apple Health here, Whoop's cloud there, Oura's app, your scale's app. Each one shows you a few charts and keeps the data. **HealthSave Observatory pulls all of it into one private place that's yours** — queryable, routable, and finally able to answer the questions that matter: *what changed, compared to my own baseline, where did it come from, and what should I look at next?*

It runs entirely on your hardware — a laptop, a NUC, a Mac mini, a Synology, a Proxmox VM. No cloud, no subscription, no one else reading your numbers. **Apple Health is the easiest way in, but it is not the boundary:** Android Health Connect, direct wearable connectors, file imports, and webhooks all land in the same canonical record.

## Just want the app?

[**HealthSave Capture**](https://apps.apple.com/app/id6759843047) (the HealthSave iOS app) is the Apple Health bridge for your Observatory — and it also runs standalone: on-device Dashboard, Trends, and Export to CSV / JSON / PDF, no account, nothing in the cloud. Self-hosting the Observatory is what adds the longitudinal record you own, the dashboard, the Body Briefs, the routes to your other tools, and the private API.

## What you get

- **Universal capture.** Apple Health (via [HealthSave Capture](https://apps.apple.com/app/id6759843047)), Android Health Connect *(in progress)*, direct wearable connectors (Whoop, Amazfit / Zepp), file imports (Garmin, Samsung / Huawei Health), and any registered webhook — all normalized into one canonical, source-tagged record you can query with normal SQL.
- **A private Observatory dashboard.** *Today vs your personal baseline*, what changed, how complete the data is, and where each number came from. The web Observatory ([`apps/web/`](apps/web/README.md)) is the primary surface; Grafana ships as an optional power-user view.
- **Evidence-linked findings & weekly Body Briefs.** Not "feed it to the cloud and hope." A deterministic statistical engine computes each finding — claim, baseline window, effect size, confidence, and what it *cannot* conclude — and a local LLM only narrates it. The **Body Brief** is the thing you come back for.
- **Source provenance you can trust.** See which device and path produced each number — and when your Apple Watch and Whoop disagree about last night's sleep, see the *disagreement* instead of a fake single truth.
- **Your own private health API + CLI.** Query your history from your scripts, notebooks, dashboards, or your own AI agents — locally, without handing your data to a third-party API vendor.
- **Route it anywhere (optional).** Home Assistant, MQTT, Grafana, webhooks, exports — your data piped to your tools, behind a policy you control.
- **A trust boundary you can audit.** Default-deny egress: raw observations never leave your host; cloud AI is opt-in and carries only derived, on-device-redacted findings.

The entire stack runs in Docker on a laptop, a NUC, a Mac mini, a Synology, or a beefy workstation — your choice. Nothing phones home.

## Capture sources

The canonical ingest model is **source-agnostic** — Apple Health is the most polished on-ramp, not the boundary. Every source resolves to the same **Source / Device / Stream** identity, so your dashboards and automations stay stable as you add devices.

| Source | How it connects | Status |
|---|---|---|
| **Apple Health** (Apple Watch, iPhone, and anything that writes to HealthKit — Oura, Garmin, Withings, etc.) | Push, via the [HealthSave Capture](https://apps.apple.com/app/id6759843047) iOS app | Shipped |
| **Whoop** | Direct poll plugin — OAuth to the Whoop API, no Apple device needed ([`plugins/sources/whoop`](plugins/sources/whoop)) | Shipped (early; bring your own Whoop developer credentials) |
| **Amazfit / Zepp** | Direct poll plugin ([`plugins/sources/amazfit`](plugins/sources/amazfit)) | Shipped (early) |
| **Garmin Connect** | CLI importer ([`scripts/import_garmin.py`](scripts/import_garmin.py)) | Shipped |
| **Samsung / Huawei Health** | CLI importer, via the Health Sync app ([`scripts/import_samsung.py`](scripts/import_samsung.py)) | Shipped |
| **Android Health Connect** | Native capture into the generic ingest API | In progress |
| **Generic webhook / native API** | Any registered source posting canonical observations (HMAC-signed) | In progress |
| **Oura** | Via Apple Health today; a direct connector (modelled on Whoop's) is on the roadmap | Planned (direct) |

Not on the list? If it writes to Apple Health, the iOS bridge forwards it automatically. Otherwise implement the `Source` plugin contract and poll it yourself — that's exactly how the Whoop and Amazfit plugins work — or post canonical observations to the generic ingest API.

## Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/) installed and running, plus a terminal. On Windows, run this inside WSL2 - `setup.sh` is a bash script.

```bash
git clone https://github.com/umutkeltek/health-data-hub.git
cd health-data-hub
./setup.sh
```

That's it. `setup.sh`:

1. Generates secure passwords and writes a `.env` for you
2. Asks if you want the AI briefing system, then **detects your RAM + GPU and recommends the right Ollama model** (you can override)
3. Brings the whole stack up with `docker compose up -d`

When it finishes, run `./setup.sh doctor` to confirm every service is healthy. The doctor prints the exact iOS-app URL to paste into [HealthSave](https://apps.apple.com/app/id6759843047) under Settings → Server Sync.

Re-running `./setup.sh` is safe - it preserves passwords and updates only the AI-related config based on your answers.

## Hardware recommendations

The AI briefing uses a local language model running through [Ollama](https://ollama.com) (a tiny daemon that runs LLMs on your own machine). Different models need different amounts of RAM. `setup.sh` reads your system RAM + GPU and suggests one - but you can pick any Ollama tag.

| System RAM | No GPU / Apple Silicon | NVIDIA GPU detected |
|---|---|---|
| < 6 GB | *too small - skip AI* | *too small - skip AI* |
| 6–10 GB | `llama3.2:1b` (~1.3 GB) | `gemma3:4b` (~3 GB) |
| 10–18 GB | `gemma3:4b` (~3 GB) | `qwen3:8b` (~5 GB) |
| 18–36 GB | `qwen3:8b` (~5 GB) | `qwen3:14b` (~9 GB) |
| 36–96 GB | `qwen3:14b` (~9 GB) | `gemma3:27b` (~17 GB) |
| > 96 GB | `llama3.3:70b` (~40 GB) | `llama4:scout` (MoE, ~40 GB) or `llama3.3:70b` |

A quick translation:

- **Apple Silicon Macs** (M1/M2/M3/M4) use unified memory, so system RAM ≈ what the model can use. A 16 GB MacBook Air handles `gemma3:4b` comfortably; a 64 GB Studio runs `qwen3:14b` with headroom.
- **Linux box with an NVIDIA GPU** - Ollama uses CUDA. The recommendation bumps a tier because the GPU absorbs most of the work.
- **AMD GPU on Linux** - Ollama can use ROCm but coverage varies; treated as CPU-only in the recommendation logic.
- **Intel Macs and Windows-without-WSL** - fall back to CPU-only conservative defaults; still works, just slower.

These picks default to the **2026 instruction-tuned generations** (Llama 3.3, Qwen 3, Gemma 3, Llama 4 Scout) because the AI briefing is a narrative-prose task — generalist chat models beat reasoning specialists like DeepSeek-R1 here. Older `llama3.1:8b` / `qwen2.5:14b` still work fine if that's what you have pulled; the table is a recommendation, not a requirement. Llama 4 Scout uses Mixture-of-Experts so only ~17 B parameters are active per token, which is why it fits the 70 B-class slot despite its 109 B total parameter count.

You can change the model later (see Troubleshooting).

If you're on something smaller than 6 GB RAM (a Pi 4, an old NAS), `setup.sh` will recommend skipping AI entirely. The ingest pipeline still runs - you just won't get the morning narrative.

## Running on Proxmox, a NAS, or a homelab box

It's plain Docker Compose, so anything that runs Docker runs this. On Proxmox specifically:

- **Easiest: a small VM.** Create a Debian 12 / Ubuntu 22.04+ VM, give it ~2 vCPU and 4 GB RAM (comfortable for ingest + TimescaleDB + Grafana), install Docker, then run `./setup.sh`. Add RAM - or pass through an NVIDIA GPU - only if you want the local AI briefing (see the table above for the RAM-to-model mapping).
- **Container route: a Docker-capable LXC.** Works too, but Docker-in-LXC wants a privileged container (or `nesting=1` + `keyctl=1`) and is fiddlier than a VM. If you're unsure, use the VM.
- **Storage.** TimescaleDB is the only stateful piece - point its Docker volume at a disk you back up. History grows slowly (roughly megabytes per month for one person), so it stays light.
- **Reaching it from your phone.** HealthSave syncs to the VM/LXC's LAN IP on port 8000, not `localhost`; `./setup.sh doctor` prints the exact URL to paste into the app.

Don't expose plain HTTP to the internet - if you need remote access, put it behind a reverse proxy (see [HTTPS / Reverse Proxy](#https--reverse-proxy)).

## How the AI analysis works

The briefing isn't "feed everything to ChatGPT and hope". It's a **two-brain system**:

- **Brain 1 - the statistical engine.** A small Python module that runs on a schedule, reads your time-series data (heart rate, HRV, sleep, etc.), computes baselines and trends, and flags anything statistically interesting (a 3-day HRV decline, a heart-rate-recovery anomaly, a sleep-stage shift). It produces structured findings, not prose.
- **Brain 2 - the narrative LLM.** A local Ollama model takes those findings and rewrites them as a short, readable briefing. It doesn't see raw numbers it doesn't need; it sees flagged findings and turns them into "Your HRV has dropped three days running while sleep efficiency stayed flat - this often shows up before a stress spike".

This split is deliberate: the math stays deterministic and auditable; the LLM only handles the part where natural language actually helps. No cloud, no per-query cost, no data leaving your network.

**Going cloud is opt-in, and redacted.** By default nothing leaves your network. If you deliberately point Brain 2 at a cloud model (`allow_cloud_egress: true`), a default-deny egress gate still guarantees raw rows never leave - only derived findings and the assembled prompt cross the boundary, and that prompt is first scrubbed on-device of any identifiers (emails, phone numbers, opaque IDs, names) via `redact_cloud_prompts` (on by default). The local Ollama path is never redacted, because that data never left.

What's included in the MVP:

- Daily HR / HRV summary
- HR / HRV anomaly detection against your rolling baseline
- HR / HRV trend detection over a configurable 30-day window
- Workout recovery hints when HR or HRV deviates from baseline
- Weekly summaries and cross-metric correlation analysis
- A `POST /api/insights/trigger` endpoint for running briefings or trend checks on demand

What's *not* yet included (and on the roadmap): goal-tracking, anomaly alerting via Home Assistant, multi-person households.

## Your first insight

Briefings need at least one full day of heart-rate data to say anything useful. Once you've synced from HealthSave at least once, you have two ways to see your first briefing:

**Option A - wait for the daily cron.** The analysis worker ticks once a day (default 7am local) and writes a fresh briefing. Easiest, but slow if you just installed.

**Option B - trigger one now.** Hit the trigger endpoint:

```bash
curl -X POST http://localhost:8000/api/insights/trigger
```

(Add `-H "X-API-Key: your-key"` if you set an `API_KEY` in `.env`.)

The response includes the run ID; you can poll `GET /api/insights/latest` for the rendered briefing once the run completes (usually 5–30 seconds depending on model size).

If the briefing comes back empty or terse, it usually means there isn't enough data yet. Sync another day's worth and trigger again.

## Connect HealthSave

The easiest way to push HealthKit data into this stack is the [HealthSave iOS app](https://apps.apple.com/app/id6759843047).

HealthSave expects a base server URL and appends the API paths itself:

`http://your-server-ip:8000`

1. Open HealthSave → Settings → Server Sync
2. Set Server URL to: `http://your-server-ip:8000`
3. (Optional) Set your API key if you configured one
4. Tap "Sync New Data"

If you're building another client, the batch ingest endpoint is:

`http://your-server-ip:8000/api/apple/batch`

The full request/response contract, including the exact `/api/apple/status` shape expected by the iOS app, is documented in [API.md](API.md).

## Troubleshooting

**The Ollama container won't start.**

```bash
docker compose logs ollama
```

The most common causes are: not enough free RAM (Ollama refuses to load a model that won't fit), the override file missing (re-run `./setup.sh` - it copies the example), or another process holding port 11434 (stop it, or edit `docker-compose.override.yml` to bind a different port).

**My briefing came back empty (or said "not enough data").**

Two things to check:

1. Has HealthSave actually synced? Hit `http://localhost:8000/api/apple/status` - if the table counts are all zero, sync from your phone first.
2. How much history do you have? The statistical engine needs at least ~24 hours of heart-rate data to compute anything. Newly-installed users typically see a real briefing on day 2.

**I want to change the model after setup.**

Edit the `OLLAMA_MODEL=` line in your `.env`, then pull the new tag and restart:

```bash
# Edit .env to set OLLAMA_MODEL=<new-tag>
docker compose exec ollama ollama pull <new-tag>
docker compose restart api
```

The tier table above is a starting point - any Ollama model tag works. Browse [ollama.com/library](https://ollama.com/library) for the full list.

**`./setup.sh doctor` says a service isn't running.**

Run `docker compose logs <service>` (e.g. `docker compose logs api`) to see why. Most first-time failures are Docker not having enough memory allocated - bump it in Docker Desktop's preferences and re-run `./setup.sh`.

---

## For developers

### Stack

FastAPI + TimescaleDB at the core; a Next.js **Observatory** web app ([`apps/web/`](apps/web/README.md)) as the primary surface; Grafana as an optional power-user view; an optional **Ollama** sidecar for local narration. Python 3.12, async SQLAlchemy with asyncpg, ruff for lint+format, pytest for tests. Ingest (`/api/apple/batch`) is a frozen v1 contract; client-facing read/query surfaces evolve under `/api/v2/`.

### Architecture

```
CAPTURE (sources in)                        SURFACES & ROUTES (out)

HealthSave Capture (Apple Health) ┐         ┌─► Observatory web app  (apps/web)
Android Health Connect *          │         │
Whoop / Amazfit  (plugins)        ├─► FastAPI ─► TimescaleDB ─┼─► Grafana  (optional)
Garmin / Samsung (importers)      │  (8000)     (canonical    │
Generic webhook / native API *    ┘             observations) ├─► Body Briefs
                                                              │     stats engine → local LLM (Ollama)
  v1 ingest  /api/apple/batch   (frozen contract)            │
  v2 ingest  /api/v2/ingest/... (evolving)        *          ├─► Private API + CLI / your agents (/api/v2)
                                                              │
                                                              └─► Routes: Home Assistant · MQTT · webhook · export

                                                                   (* in progress)
```

The math stays deterministic and auditable; the LLM only narrates. Raw observations
never cross the host boundary — see [Privacy & the egress boundary](#how-the-ai-analysis-works).

### What gets synced

The server receives and stores 120+ HealthKit metrics:

| Table | Data |
|-------|------|
| `heart_rate` | Continuous HR from Apple Watch / Whoop |
| `hrv` | Heart rate variability (SDNN) |
| `blood_oxygen` | SpO2 readings, with source labels for provider data |
| `daily_activity` | Steps, distance, calories, exercise minutes |
| `sleep_sessions` | Sleep duration, stages, respiratory rate |
| `workouts` | Workout type, duration, HR zones, source labels |
| `quantity_samples` | Catch-all for optional HealthKit metrics and provider aggregates such as Whoop recovery score, resting HR, strain, and sleep aggregates |

### Manual quick-start (without `setup.sh`)

```bash
cp .env.example .env
# Edit .env with your passwords

docker compose up -d
```

This starts:
- **TimescaleDB** on port 5432
- **FastAPI** on port 8000
- **Grafana** on port 3000 (default login: admin / your GRAFANA_PASSWORD)

`./setup.sh` is the easier path — it generates the passwords for you. On the
manual path, set `DB_PASSWORD` and `GRAFANA_PASSWORD` in `.env` first (compose
requires them, so the project never ships guessable defaults).

The database port and Grafana are bound to `127.0.0.1` by default, so they are
available for local tooling without being exposed on your LAN. To reach Grafana
from another device, set `GRAFANA_BIND=0.0.0.0` in `.env`.

To opt into Ollama manually, copy `docker-compose.override.yml.example` to `docker-compose.override.yml`, copy `config.yaml.example` to `config.yaml`, set `analysis.daily_briefing.enabled` and `analysis.anomaly_detection.enabled` to `true`, and set `OLLAMA_MODEL` in `.env` to the tag you want.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/health` | GET | App-friendly health check |
| `/ready` | GET | API plus database readiness check |
| `/api/apple/batch` | POST | Receive metric batch from the client bridge |
| `/api/apple/status` | GET | Return flat per-table status objects |
| `/api/v2/sync/runs/latest` | GET | Optional latest HealthSave delivery receipt |
| `/api/v2/sync/coverage` | GET | Optional metric-level receipt coverage |
| `/api/insights/latest` | GET | Most recent briefing (if AI enabled) |
| `/api/insights/anomalies` | GET | Recent anomaly findings, filterable by `since` and `severity` |
| `/api/insights/trends` | GET | Recent HR / HRV trend findings, filterable by `period=30d` |
| `/api/insights/trigger` | POST | Run an analysis pass now (if AI enabled) |
| `/metrics` | GET | Prometheus text exposition (no auth, DB-independent) |

`/api/apple/status` intentionally returns top-level metric objects, not a
wrapped `{"status":"ok","counts":...}` payload. See [API.md](API.md) for
the compatibility contract.

### Prometheus Metrics

`/metrics` exposes runtime counters and a histogram in Prometheus text
exposition format. The endpoint is unauthenticated by design (so scrapers
do not need `X-API-Key`) and does not touch the database, so it returns
200 even when Postgres is down — safe to use as a liveness target.

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `hdh_ingest_batches_total` | counter | `metric` | Batches accepted by `/api/apple/batch`, including empty ones |
| `hdh_ingest_rows_total` | counter | `metric` | Rows persisted per metric (cumulative) |
| `hdh_ingest_duration_seconds` | histogram | `metric` | End-to-end batch handler latency |
| `hdh_ai_briefing_runs_total` | counter | `job`, `result` | Daily briefing / anomaly check / trend analysis runs by outcome (`success` / `failure`) |

Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: health-data-hub
    metrics_path: /metrics
    static_configs:
      - targets: ['health-data-hub:8000']  # or 'localhost:8000' for host scrape
```

Sample Grafana panel — rows ingested per second, broken down by metric
(Time series panel):

```promql
sum by (metric) (rate(hdh_ingest_rows_total[5m]))
```

Pair `rate(hdh_ai_briefing_runs_total{result="failure"}[1h])` with an
alert if you want a heads-up when nightly analysis starts failing.

### Garmin Imports

Garmin Connect users can sideload data into the same `/api/apple/batch`
endpoint via `scripts/import_garmin.py`. The script supports the bulk
"Export Your Data" ZIP, individual FIT/TCX activity files, and the
JSON files Garmin includes for daily steps and sleep stages.

Install the optional FIT-parsing dependency once:

```bash
pip install -e ".[garmin]"   # adds fitparse for FIT activity files
```

(TCX, JSON, and ZIP parsing use only the standard library.)

Run it:

```bash
# Bulk export ZIP - walks every supported file inside
python scripts/import_garmin.py \
  --zip GarminConnect_Export.zip \
  --server http://localhost:8000 \
  --api-key $HDH_API_KEY

# Individual files
python scripts/import_garmin.py --tcx run.tcx --steps-json steps.json --sleep-json sleep.json

# Sanity-check the payload before sending
python scripts/import_garmin.py --tcx run.tcx --dry-run
```

Mapping:

| Source | HealthSave metric | Server table |
|--------|-------------------|--------------|
| FIT/TCX heart-rate records | `heart_rate` | `heart_rate` |
| Daily step totals (JSON) | `step_count` | `daily_activity.steps` |
| Sleep stages (JSON) | `sleep_analysis` | `sleep_sessions` + `sleep_stages` |

### Samsung / Huawei Health Sync Imports

Android users can sideload Samsung Health or Huawei Health data exported through
the Android [Health Sync](https://healthsync.app/) app via
`scripts/import_samsung.py`. The importer reads Health Sync CSV folders and sends
the same `/api/apple/batch` payload shape as the iOS app, so deduplication,
auditing, sync receipts, and dashboards all stay on the normal ingest path.

Supported Health Sync folders:

| Folder | HealthSave metric | Server table |
|--------|-------------------|--------------|
| `Health Sync Steps/` | `step_count` | `daily_activity.steps` |
| `Health Sync Heart rate/` | `heart_rate` | `heart_rate` |
| `Health Sync Sleep/` | `sleep_analysis` | `sleep_sessions` + `sleep_stages` |
| `Health Sync Weight/` | `body_mass`, `body_fat_percentage` | `quantity_samples` |
| `Health Sync Oxygen saturation/` | `oxygen_saturation` | `blood_oxygen` |

Run it:

```bash
# Sanity-check the export before sending
python scripts/import_samsung.py /path/to/health-sync-export --dry-run

# Send to a local datahub
python scripts/import_samsung.py /path/to/health-sync-export \
  --server http://localhost:8000 \
  --api-key $HDH_API_KEY
```

### Grafana Dashboards

A curated starter dashboard set is included in `deploy/grafana/`, so a fresh `docker compose up -d` should bring Grafana up with the datasource and the supported dashboards already wired.

> **Heads-up:** the **HealthSave Observatory** web app under [`apps/web/`](apps/web/README.md) is the primary, insight-first surface and the direction of the project. Grafana is kept as an **optional power-user view** — it remains the dashboard bundled in the default `docker compose` stack while the Observatory web app is being wired into the default deployment.

Included files:
- `deploy/grafana/provisioning/datasources/healthsave.yaml`
- `deploy/grafana/provisioning/dashboards/default.yaml`
- `deploy/grafana/dashboards/`

Supported dashboards loaded automatically:

| Dashboard | File | Depends On | Status | Notes |
|-----------|------|------------|--------|-------|
| HealthSave Overview | `deploy/grafana/dashboards/healthsave-overview.json` | `heart_rate`, `hrv`, `blood_oxygen`, `daily_activity`, `sleep_sessions`, `workouts` | Supported | Best first dashboard for a fresh install |
| Activity & Movement | `deploy/grafana/dashboards/activity.json` | `daily_activity`, `quantity_samples` | Supported | Gait-related panels only populate if those optional metrics are synced |
| Heart | `deploy/grafana/dashboards/heart.json` | `heart_rate`, `hrv`, `quantity_samples` | Supported | Source-aware heart-rate, HRV, SpO2, and respiratory panels |
| Sleep | `deploy/grafana/dashboards/sleep.json` | `sleep_sessions`, `sleep_stages`, `quantity_samples` | Supported | Apple sleep sessions plus provider aggregate sleep metrics |
| Insights | `deploy/grafana/dashboards/insights.json` | `heart_rate`, `hrv`, `blood_oxygen`, `body_temperature`, `quantity_samples`, `sleep_sessions`, `workouts` | Supported | Cross-source comparison and Whoop recovery/sleep/strain views through the public schema |
| Workouts | `deploy/grafana/dashboards/workouts.json` | `workouts` | Supported | Focused workout view with type, duration, calories, and HR panels |

The datasource is auto-provisioned - no manual setup needed.

### Home Assistant Integration

There are two supported Home Assistant paths:

1. **MQTT bridge (recommended):** Health Data Hub reads TimescaleDB and publishes retained Home Assistant MQTT discovery + state topics. This keeps Home Assistant out of the database and works even when Grafana is deployed separately.
2. **Direct SQL package (legacy/example):** Home Assistant queries TimescaleDB directly using `integrations/home-assistant/healthsave-package.yaml`.

The bridge publishes in two layers each cycle:

**Aggregate parent device** (one device, one state topic, the legacy shape):

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

**Per-source sub-devices** (one device per distinct `source_id` seen in recent data — Apple Watch, Whoop, iPhone, etc.):

- Retained state topic: `healthsave/source/<slug>/state` (one JSON payload per source)
- Discovery topics: `homeassistant/sensor/healthsave_<slug>/<metric>/config`
- Linked to the parent via Home Assistant's `via_device` so HA nests sub-devices under the parent.
- Metrics carried per sub-device: `heart_rate`, `hrv_latest_ms`, `steps_today`, `last_sleep_hours`. Only metrics with a recent non-null value get a discovery message, so HA never sees ghost entities.

Example: a household running both an Apple Watch and a Whoop sees:
- `sensor.healthsave_apple_watch_heart_rate`, `_hrv_latest_ms`, `_steps_today`, `_last_sleep_hours`
- `sensor.healthsave_whoop_heart_rate`, `_hrv_latest_ms`, `_last_sleep_hours` (no `_steps_today` if Whoop hasn't logged any).

Source attribution comes from `source_id` on the ingestion tables (added to `daily_activity` and `sleep_sessions` in migration 009; native to `heart_rate` / `hrv` since v1). Rows with NULL `source_id` collapse to a single `sensor.healthsave_unknown_*` sub-device so legacy data never fragments into empty entities.

Both layers share `healthsave/status` so HA marks every sub-device offline together if the bridge stops.

**Legacy MQTT namespace migration.** Fresh installs should keep the
primary `HA_MQTT_STATE_TOPIC_PREFIX`, `HA_MQTT_DEVICE_IDENTIFIER`, and
`HA_MQTT_DEVICE_NAME` values on `healthsave` / `HealthSave`. If an
existing Home Assistant install still has dashboards or automations on
an older namespace, set `HA_MQTT_LEGACY_STATE_TOPIC_PREFIX` plus the
matching legacy device identifier/name. The bridge then publishes both
shapes from the same Data Hub service so Home Assistant can be migrated
one entity at a time.

```bash
HA_MQTT_STATE_TOPIC_PREFIX=healthsave
HA_MQTT_DEVICE_IDENTIFIER=healthsave
HA_MQTT_DEVICE_NAME=HealthSave
HA_MQTT_LEGACY_STATE_TOPIC_PREFIX=<old-prefix>
HA_MQTT_LEGACY_DEVICE_IDENTIFIER=<old-device-id>
HA_MQTT_LEGACY_DEVICE_NAME=<old-display-name>
```

Enable it with Docker Compose. Two patterns:

**(a) Bring your own broker.** Point the bridge at an MQTT server you already run:

```bash
HA_MQTT_ENABLED=true \
HA_MQTT_BROKER=<your-mqtt-host> \
HA_MQTT_USERNAME=<optional-user> \
HA_MQTT_PASSWORD=<optional-password> \
docker compose --profile home-assistant up -d homeassistant-mqtt
```

**(b) Use the bundled broker.** Add the `mosquitto` profile and the
stack runs an `eclipse-mosquitto:2` container alongside the bridge.
The bridge's default `HA_MQTT_BROKER=mqtt` resolves through docker DNS,
and host port `1883` is published so a Home Assistant install on the
same LAN can also connect by host IP. Persistence is on a docker
volume so retained messages survive restarts.

```bash
HA_MQTT_ENABLED=true \
docker compose --profile mosquitto --profile home-assistant up -d
```

The bundled broker defaults to anonymous-on-LAN. To require auth,
overlay a `docker-compose.override.yml` that flips
`allow_anonymous false` and mounts a password file — the conf at
`deploy/mosquitto/mosquitto.conf` is read-only so the override is the
right seam.

Useful defaults:

- Discovery prefix: `homeassistant`
- State prefix: `healthsave`
- Device identifier: `healthsave`
- Publish interval: `60` seconds

Direct SQL example files remain available for setups that prefer DB polling:
- `integrations/home-assistant/healthsave-package.yaml`
- `integrations/home-assistant/secrets.example.yaml`

Shareable dashboard examples are in `integrations/home-assistant/`:
- `integrations/home-assistant/README.md`
- `integrations/home-assistant/nervous-system-core-package.yaml`
- `integrations/home-assistant/dashboards/nervous-system-core.raw-lovelace.json`

### Community Backends

The ingest API is intentionally simple so anyone can build a compatible backend for their own stack. The first community implementation is already live:

- **[health-data-to-mqtt](https://github.com/bietiekay/health-data-to-mqtt)** by [@bietiekay](https://github.com/bietiekay) - A lightweight Node.js server that stores raw JSON and forwards selected metrics to MQTT. Built for alerting and home automation pipelines where MQTT is the primary transport.

If you've built a compatible backend, open an issue or PR and we'll add it here. The full API contract including every supported metric is documented in [API.md](API.md).

### Pluggable Storage Backends

The default backend is TimescaleDB (a Postgres extension), which is what `setup.sh` provisions. If you already run a different time-series store and don't want to add a second one, the ingest path is pluggable: write a Python module that implements the `IngestStorage` protocol, register it, and point the server at it via env vars.

**Built-in backends:**

| Name | Backed by | Audit log | Notes |
|------|-----------|-----------|-------|
| `postgres` (default) | TimescaleDB hypertables | yes (`raw_ingestion_log`) | Joins, transactions, continuous aggregates |

**Selecting a backend:**

```bash
HDH_STORAGE_BACKEND=postgres docker compose up -d   # explicit (also the default)
```

**Writing your own (e.g. InfluxDB, ClickHouse, DuckDB, MQTT-only):**

1. Implement `server.ingestion.storage.IngestStorage` in your own package — two methods: `get_or_create_device()` and `ingest_metric()`.
2. Optionally implement `server.ingestion.storage.AuditLog` if your store supports an audit row pattern. Append-only stores (InfluxDB) skip this; the route notices and skips audit calls.
3. Register a factory at module-import time:

   ```python
   # mycorp_health/influx_backend.py
   from server.ingestion.registry import register_backend

   def _influx_factory(config):
       from .influx_storage import InfluxIngestStorage
       return InfluxIngestStorage(config), None  # append-only, no AuditLog

   register_backend("influxdb", _influx_factory)
   ```

4. Tell the server to load your plugin and use it:

   ```bash
   HDH_STORAGE_PLUGINS=mycorp_health.influx_backend \
   HDH_STORAGE_BACKEND=influxdb \
   docker compose up -d
   ```

`HDH_STORAGE_PLUGINS` is comma-separated — multiple plugin modules are imported in order before the backend lookup runs. A failed plugin import is logged but doesn't abort startup, so a missing optional dependency degrades to "fall back to the built-in default" rather than "server doesn't boot."

The protocols, the registry, and a worked example live in `server/ingestion/storage.py` and `server/ingestion/registry.py`. If you ship a backend, open an issue and we'll list it under [Community Backends](#community-backends).

### Deduplication

All ingestion is idempotent:
- Unique indexes on first-class metric identity columns
- `INSERT ... ON CONFLICT DO UPDATE` for upsert behavior
- In-memory dedup within each batch to avoid PG errors

You can safely re-sync or retry without inflating your data.

The API also stores each received batch in `raw_ingestion_log` before
processing, then marks it processed after a successful commit. That gives you a
minimal audit trail and a useful starting point if you ever need replay tooling.

### Updating Existing Installs

Fresh installs load `db/schema.sql` automatically. Existing Docker volumes keep
their original schema, so the Compose stack runs the migration service before
the API, worker, agents, or Home Assistant bridge start:

```bash
docker compose up -d --build
```

To run the same migration pass explicitly:

```bash
docker compose run --rm migrate
```

The runner records applied files in `schema_migrations`, so re-runs are safe.
Migration files still live in `db/migrations/` for review and manual recovery.
The current set starts at `db/migrations/001_audit_hardening.sql` and includes
later additive upgrades such as `db/migrations/002_analysis_tables.sql` and
`db/migrations/008_oauth_tokens.sql`; files apply in filename order.

### Multi-user / Household

Every metric table carries an `owner_id` UUID. Single-user installs need
to do nothing — when the `X-User-Id` header is absent, ingest writes
under the sentinel UUID `00000000-0000-0000-0000-000000000001` and the
schema-level default backfills any pre-migration rows to the same value.

To split a household across multiple residents:

1. Pick a UUID per person (any v4 UUID works — `python -c "import uuid; print(uuid.uuid4())"`).
2. Configure each HealthSave client / import script to send that UUID as the
   `X-User-Id` header on every `POST /api/apple/batch` call.
3. Filter Grafana panels by `owner_id` (add a dashboard variable bound to the
   `SELECT DISTINCT owner_id FROM heart_rate` query, then drop `WHERE owner_id = '$owner'`
   into each panel query).

Existing single-user installs keep working untouched if step 2 is skipped.
The unique indexes on every metric table include `owner_id`, so two
residents can have a sample at the same `(time, device_id)` without
collisions, and re-syncing from one client remains idempotent.

### Development

Local verification uses the same commands as CI:

```bash
python3.12 -m pip install -e ".[dev]"
python3.12 -m ruff format --check .
python3.12 -m ruff check .
python3.12 -m pytest -q
docker build -t health-data-hub-dev .
```

The project targets Python 3.12, matching the Docker image and CI runtime.

The CI workflow runs formatting, linting, tests, and a Docker build on every
push and pull request to `main`.

### HTTPS / Reverse Proxy

For production, put a reverse proxy in front of the API:

```yaml
# Add to docker-compose.yml
  caddy:
    image: caddy:2-alpine
    ports:
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
```

```
# Caddyfile
health.yourdomain.com {
    reverse_proxy api:8000
}
```

Recommended production posture:
- Set a long random `API_KEY` in `.env` and in the HealthSave app.
- Keep TimescaleDB bound to localhost or a private Docker network.
- Terminate HTTPS at your reverse proxy.
- Back up the `db_data` Docker volume regularly.
- Upgrade `TIMESCALE_IMAGE` and `GRAFANA_IMAGE` deliberately, not via `latest`.

### Derived Metrics

The schema includes continuous aggregates for common derived metrics:

- `hr_hourly` - Hourly avg/min/max heart rate
- `sleep_daily` - Daily sleep stage breakdown

Add your own with TimescaleDB continuous aggregates:

```sql
-- Example: weekly HRV trend
CREATE MATERIALIZED VIEW hrv_weekly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 week', time) AS bucket,
    device_id,
    avg(value_ms) AS avg_hrv,
    min(value_ms) AS min_hrv,
    max(value_ms) AS max_hrv
FROM hrv
GROUP BY bucket, device_id
WITH NO DATA;
```

### Roadmap

HealthSave Observatory is built in phases — from a release-grade core and a stable
**Source / Device / Stream** identity, to the **Observatory** web surface, the weekly
**Body Brief** loop, the **agent surface** (CLI + MCP + scoped tokens), universal capture
(Android Health Connect + generic webhook), and a thin routing layer for Home Assistant /
MQTT / webhook / export. Near-term focus areas:

- Ship the Observatory web app as the default surface; keep Grafana as an optional view
- Weekly evidence-linked Body Briefs and a first-class finding-card schema
- A private CLI + local MCP server so your own agents can query your body data
- Android Health Connect + a generic, HMAC-signed ingest envelope
- Trend-based alerts and recovery-aware automations via Home Assistant

## License

The product core is **source-available** under the [Elastic License 2.0](LICENSE)
(self-host freely; you may not offer it to third parties as a managed service). The
protocol and client layer (`contracts/`, the API client, and the plugin SDK) is
**Apache-2.0** so anything can speak the format. See [LICENSING.md](LICENSING.md) for
the per-path map and [TRADEMARK.md](TRADEMARK.md) for the name policy.
