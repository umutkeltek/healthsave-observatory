# Health Data Hub

Self-hosted server stack for ingesting HealthKit-derived data into TimescaleDB and visualizing it with Grafana.

It currently works with the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app, which acts as a thin HealthKit bridge with background sync, but the backend is intentionally named more broadly so it can evolve beyond a single client over time.

**Stack:** FastAPI + TimescaleDB + Grafana

## Why This Exists

Apple Health is great for collection, but much less useful once you want long-term storage, custom queries, or home automation built on top of your own data.

This server exists to make that data portable and useful:
- Store full history in your own database
- Query it with normal SQL and time-series tooling
- Build Grafana dashboards without being limited to Apple's UI
- Feed selected metrics into systems like Home Assistant

The goal is not to replace the Health app. It is to provide a simple self-hosted backend that makes your health data easier to inspect, automate, and keep long-term.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your passwords

docker compose up -d
```

This starts:
- **TimescaleDB** on port 5432
- **FastAPI** on port 8000
- **Grafana** on port 3000 (default login: admin / your GRAFANA_PASSWORD)

## First 5 Minutes

If this is your first run, this is the shortest path to confirming the stack is alive:

1. Start the stack with `docker compose up -d`
2. Check the API health endpoint at `http://localhost:8000/health`
3. Open Grafana at `http://localhost:3000` and log in with `admin` and your `GRAFANA_PASSWORD`
4. Confirm the `HealthSave` PostgreSQL datasource is present
5. Open the `HealthSave Overview` dashboard
6. In the [HealthSave](https://apps.apple.com/app/id6759843047) app, set Server Sync to the base server URL: `http://your-server-ip:8000`
7. Run a sync and refresh Grafana

What you should expect after the first successful sync:
- `/api/apple/status` starts showing non-zero table counts
- `HealthSave Overview` begins to populate with heart rate, HRV, SpO2, activity, sleep, and workout data
- The activity and workout dashboards become useful immediately if those datasets were included in the sync

## Connect HealthSave

The easiest way to push HealthKit data into this stack is with the [HealthSave iOS app](https://apps.apple.com/app/id6759843047).

HealthSave expects a base server URL and appends the API paths itself:

`http://your-server-ip:8000`

1. Open HealthSave → Settings → Server Sync
2. Set Server URL to: `http://your-server-ip:8000`
3. (Optional) Set your API key if you configured one
4. Tap "Sync New Data"

If you are building another client, the batch ingest endpoint is:

`http://your-server-ip:8000/api/apple/batch`

The full request/response contract, including the exact `/api/apple/status`
shape expected by the iOS app, is documented in [API.md](API.md).

## What Gets Synced

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

## Grafana Dashboards

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

The datasource is auto-provisioned — no manual setup needed.

## Home Assistant Examples

Example Home Assistant config is included in `home-assistant/` for people who want to query TimescaleDB directly and turn selected metrics into entities and automations.

Included files:
- `home-assistant/healthsave-package.yaml`
- `home-assistant/secrets.example.yaml`

Recommended flow:
1. Add a read-only PostgreSQL user for Home Assistant if possible
2. Point `healthsave_db_url` at your TimescaleDB instance
3. Copy `healthsave-package.yaml` into your Home Assistant packages directory
4. Restart Home Assistant and adjust the example thresholds and entity IDs for your setup

## Roadmap

This community release is intentionally small and focused on the ingestion pipeline first.

Next things to improve:
- More dashboard polish and curation across recovery, workouts, and long-term trends
- More Home Assistant examples for different trigger styles
- Production deployment notes for reverse proxy, auth, backups, and retention

## Architecture

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
    ▼
Grafana (port 3000)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/health` | GET | App-friendly health check |
| `/api/apple/batch` | POST | Receive metric batch from the client bridge |
| `/api/apple/status` | GET | Return flat per-table status objects |

`/api/apple/status` intentionally returns top-level metric objects, not a
wrapped `{"status":"ok","counts":...}` payload. See [API.md](API.md) for
the compatibility contract.

## Deduplication

All ingestion is idempotent:
- Unique indexes on `(time, device_id)` for every hypertable
- `INSERT ... ON CONFLICT DO UPDATE` for upsert behavior
- In-memory dedup within each batch to avoid PG errors

You can safely re-sync or retry without inflating your data.

## HTTPS / Reverse Proxy

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

## Derived Metrics

The schema includes continuous aggregates for common derived metrics:

- `hr_hourly` — Hourly avg/min/max heart rate
- `sleep_daily` — Daily sleep stage breakdown

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
