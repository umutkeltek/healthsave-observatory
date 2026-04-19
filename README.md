# Health Data Hub

[![CI](https://github.com/umutkeltek/health-data-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/umutkeltek/health-data-hub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/umutkeltek/health-data-hub)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515.svg?logo=postgresql&logoColor=white)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20LLM-000000.svg)](https://ollama.com/)

> **Self-hosted Apple Health server** - sync HealthKit data from your iPhone and Apple Watch into TimescaleDB, visualize it in Grafana, and get an AI-written daily briefing via a local Ollama model. Private. Local-first. Your data stays on your hardware.

**Keywords:** `apple-health` · `healthkit` · `self-hosted` · `quantified-self` · `timescaledb` · `grafana` · `fastapi` · `ollama` · `local-llm` · `home-assistant` · `docker` · `privacy` · `health-data` · `wearables`

Your own server, on your own hardware, turning the health data your phone already collects into an AI-written daily briefing - no cloud, no subscription, no one else reading your numbers.

You point your iPhone at it. It stores everything from your Apple Watch (heart rate, HRV, SpO2, sleep, workouts, steps, and more), graphs it in Grafana, and - if you turn it on - runs a small local AI model that writes you a short narrative every morning about how your body is actually doing.

## What you get

- A long-term store for every Apple Health metric your phone collects, queryable with normal SQL
- A set of ready-made Grafana dashboards (heart, sleep, activity, workouts) that work the moment data starts flowing
- An optional AI briefing system that turns numbers into plain English ("HRV trended down three days in a row, sleep was light last night, expect a low-energy morning")
- A clean ingest API anyone can build against - the iOS app is one client, your own scripts can be another
- Drop-in examples for piping selected metrics into Home Assistant for automations

The entire stack runs in Docker on a laptop, a NUC, a Mac mini, a Synology, or a beefy workstation - your choice. Nothing phones home.

## Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/) installed and running, plus a terminal. On Windows, run this inside WSL2 - `setup.sh` is a bash script.

```bash
git clone https://github.com/<your-fork>/datahub.git
cd datahub
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
| 6–10 GB | `llama3.2:1b` (~1.3 GB) | `llama3.2:3b` |
| 10–18 GB | `llama3.2:3b` (~2 GB) | `llama3.1:8b` |
| 18–36 GB | `llama3.1:8b` (~4.7 GB) | `llama3.1:8b` |
| 36–96 GB | `llama3.1:8b` (proven default) | `qwen2.5:14b` |
| > 96 GB | `qwen2.5:32b` or `llama3.1:70b` | `llama3.1:70b` |

A quick translation:

- **Apple Silicon Macs** (M1/M2/M3/M4) use unified memory, so system RAM ≈ what the model can use. A 16 GB MacBook Air handles `llama3.2:3b` comfortably; a 64 GB Studio runs `llama3.1:8b` with headroom.
- **Linux box with an NVIDIA GPU** - Ollama uses CUDA. The recommendation bumps a tier because the GPU absorbs most of the work.
- **AMD GPU on Linux** - Ollama can use ROCm but coverage varies; treated as CPU-only in the recommendation logic.
- **Intel Macs and Windows-without-WSL** - fall back to CPU-only conservative defaults; still works, just slower.

You can change the model later (see Troubleshooting).

If you're on something smaller than 6 GB RAM (a Pi 4, an old NAS), `setup.sh` will recommend skipping AI entirely. The ingest pipeline still runs - you just won't get the morning narrative.

## How the AI analysis works

The briefing isn't "feed everything to ChatGPT and hope". It's a **two-brain system**:

- **Brain 1 - the statistical engine.** A small Python module that runs on a schedule, reads your time-series data (heart rate, HRV, sleep, etc.), computes baselines and trends, and flags anything statistically interesting (a 3-day HRV decline, a heart-rate-recovery anomaly, a sleep-stage shift). It produces structured findings, not prose.
- **Brain 2 - the narrative LLM.** A local Ollama model takes those findings and rewrites them as a short, readable briefing. It doesn't see raw numbers it doesn't need; it sees flagged findings and turns them into "Your HRV has dropped three days running while sleep efficiency stayed flat - this often shows up before a stress spike".

This split is deliberate: the math stays deterministic and auditable; the LLM only handles the part where natural language actually helps. No cloud, no per-query cost, no data leaving your network.

What's included in the MVP:

- Daily HR / HRV summary
- HR / HRV anomaly detection against your rolling baseline
- HR / HRV trend detection over a configurable 30-day window
- Workout recovery hints when HR or HRV deviates from baseline
- A `POST /api/insights/trigger` endpoint for running briefings or trend checks on demand

What's *not* yet included (and on the roadmap): goal-tracking, anomaly alerting via Home Assistant, multi-person households, correlation analysis, weekly summaries.

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

FastAPI + TimescaleDB + Grafana, plus an optional Ollama sidecar for the LLM. Python 3.12, async SQLAlchemy with asyncpg, ruff for lint+format, pytest for tests.

### Architecture

```
iPhone (HealthSave app)
    │
    │  POST /api/apple/batch (JSON over HTTPS)
    │
    ▼
FastAPI (port 8000)
    │
    │  INSERT ... ON CONFLICT DO UPDATE (idempotent)
    │
    ▼
TimescaleDB (port 5432)
    │
    │  SQL queries + continuous aggregates
    │
    ├──────────────────────────────┐
    ▼                              ▼
Grafana (port 3000)        Analysis worker
                                   │
                                   │  findings (structured)
                                   ▼
                           Ollama (port 11434)
                                   │
                                   │  briefing (prose)
                                   ▼
                           /api/insights/latest
```

### What gets synced

The server receives and stores 120+ HealthKit metrics:

| Table | Data |
|-------|------|
| `heart_rate` | Continuous HR from Apple Watch / Whoop |
| `hrv` | Heart rate variability (SDNN) |
| `blood_oxygen` | SpO2 readings |
| `daily_activity` | Steps, distance, calories, exercise minutes |
| `sleep_sessions` | Sleep duration, stages, respiratory rate |
| `workouts` | Workout type, duration, HR zones |
| `quantity_samples` | Catch-all for any other HealthKit metric |

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

The database port is bound to `127.0.0.1` by default so it is available for
local tooling without being exposed on your LAN.

To opt into Ollama manually, copy `docker-compose.override.yml.example` to `docker-compose.override.yml`, copy `config.yaml.example` to `config.yaml`, set `analysis.daily_briefing.enabled` and `analysis.anomaly_detection.enabled` to `true`, and set `OLLAMA_MODEL` in `.env` to the tag you want.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/health` | GET | App-friendly health check |
| `/ready` | GET | API plus database readiness check |
| `/api/apple/batch` | POST | Receive metric batch from the client bridge |
| `/api/apple/status` | GET | Return flat per-table status objects |
| `/api/insights/latest` | GET | Most recent briefing (if AI enabled) |
| `/api/insights/anomalies` | GET | Recent anomaly findings, filterable by `since` and `severity` |
| `/api/insights/trends` | GET | Recent HR / HRV trend findings, filterable by `period=30d` |
| `/api/insights/trigger` | POST | Run an analysis pass now (if AI enabled) |

`/api/apple/status` intentionally returns top-level metric objects, not a
wrapped `{"status":"ok","counts":...}` payload. See [API.md](API.md) for
the compatibility contract.

### Grafana Dashboards

A curated starter dashboard set is included in `grafana/`, so a fresh `docker compose up -d` should bring Grafana up with the datasource and the supported dashboards already wired.

Included files:
- `grafana/provisioning/datasources/healthsave.yaml`
- `grafana/provisioning/dashboards/default.yaml`
- `grafana/dashboards/`

Supported dashboards loaded automatically:

| Dashboard | File | Depends On | Status | Notes |
|-----------|------|------------|--------|-------|
| HealthSave Overview | `grafana/dashboards/healthsave-overview.json` | `heart_rate`, `hrv`, `blood_oxygen`, `daily_activity`, `sleep_sessions`, `workouts` | Supported | Best first dashboard for a fresh install |
| Activity & Movement | `grafana/dashboards/activity.json` | `daily_activity`, `quantity_samples` | Supported | Gait-related panels only populate if those optional metrics are synced |
| Workouts | `grafana/dashboards/workouts.json` | `workouts` | Supported | Focused workout view with type, duration, calories, and HR panels |

The datasource is auto-provisioned - no manual setup needed.

### Home Assistant Examples

Example Home Assistant config is included in `home-assistant/` for people who want to query TimescaleDB directly and turn selected metrics into entities and automations.

Included files:
- `home-assistant/healthsave-package.yaml`
- `home-assistant/secrets.example.yaml`

Recommended flow:
1. Add a read-only PostgreSQL user for Home Assistant if possible
2. Point `healthsave_db_url` at your TimescaleDB instance
3. Copy `healthsave-package.yaml` into your Home Assistant packages directory
4. Restart Home Assistant and adjust the example thresholds and entity IDs for your setup

### Community Backends

The ingest API is intentionally simple so anyone can build a compatible backend for their own stack. The first community implementation is already live:

- **[health-data-to-mqtt](https://github.com/bietiekay/health-data-to-mqtt)** by [@bietiekay](https://github.com/bietiekay) - A lightweight Node.js server that stores raw JSON and forwards selected metrics to MQTT. Built for alerting and home automation pipelines where MQTT is the primary transport.

If you've built a compatible backend, open an issue or PR and we'll add it here. The full API contract including every supported metric is documented in [API.md](API.md).

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

Fresh installs load `schema.sql` automatically. Existing Docker volumes keep
their original schema, so apply migrations manually when upgrading:

```bash
docker compose exec -T db psql -U healthsave -d healthsave < migrations/001_audit_hardening.sql
docker compose exec -T db psql -U healthsave -d healthsave < migrations/002_analysis_tables.sql
```

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

This community release is intentionally small and focused on the ingestion pipeline plus the first slice of AI briefings.

Next things to improve:
- More dashboard polish and curation across recovery, workouts, and long-term trends
- Goal tracking and trend-based alerts wired into Home Assistant
- More comprehensive analysis windows (monthly / quarterly trends)
- Production deployment notes for reverse proxy, auth, backups, and retention
