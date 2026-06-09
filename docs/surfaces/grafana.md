# Grafana Dashboards

Grafana is the **optional, bundled-today** power-user view for HealthSave Observatory. A curated starter dashboard set ships in `deploy/grafana/`, so a fresh `docker compose up -d` brings Grafana up with the datasource and the supported dashboards already wired.

Grafana is not the identity of the project. The [Observatory web app](observatory-web.md) is the primary, insight-first surface and the direction of HealthSave Observatory; Grafana remains the dashboard bundled in the default `docker compose` stack while the Observatory web app is being wired into the default deployment. If you want a raw, chart-first metric explorer, Grafana is it.

## What's bundled

A fresh install auto-provisions:

- `deploy/grafana/provisioning/datasources/healthsave.yaml` — the TimescaleDB datasource (no manual setup needed)
- `deploy/grafana/provisioning/dashboards/default.yaml` — the provisioning manifest
- `deploy/grafana/dashboards/` — the dashboard JSON

Grafana listens on port 3000 (default login: `admin` / your `GRAFANA_PASSWORD`). It is bound to `127.0.0.1` by default so it is available for local tooling without being exposed on your LAN. To reach it from another device, set `GRAFANA_BIND=0.0.0.0` in `.env`.

## Supported dashboards

These dashboards load automatically:

| Dashboard | File | Depends on | Notes |
|---|---|---|---|
| **HealthSave Overview** | `deploy/grafana/dashboards/healthsave-overview.json` | `heart_rate`, `hrv`, `blood_oxygen`, `daily_activity`, `sleep_sessions`, `workouts` | Best first dashboard for a fresh install |
| **Activity & Movement** | `deploy/grafana/dashboards/activity.json` | `daily_activity`, `quantity_samples` | Gait-related panels only populate if those optional metrics are synced |
| **Heart** | `deploy/grafana/dashboards/heart.json` | `heart_rate`, `hrv`, `quantity_samples` | Source-aware heart-rate, HRV, SpO2, and respiratory panels |
| **Sleep** | `deploy/grafana/dashboards/sleep.json` | `sleep_sessions`, `sleep_stages`, `quantity_samples` | Apple sleep sessions plus provider aggregate sleep metrics |
| **Insights** | `deploy/grafana/dashboards/insights.json` | `heart_rate`, `hrv`, `blood_oxygen`, `body_temperature`, `quantity_samples`, `sleep_sessions`, `workouts` | Cross-source comparison and Whoop recovery / sleep / strain views through the public schema |
| **Workouts** | `deploy/grafana/dashboards/workouts.json` | `workouts` | Focused workout view with type, duration, calories, and HR panels |

Panels that depend on optional metrics stay empty until those metrics are synced — that's expected, not a misconfiguration.

## Building your own panels

Grafana reads the canonical TimescaleDB schema directly, so any panel you can express in SQL works. For multi-person households, filter panels by `owner_id` (add a dashboard variable bound to `SELECT DISTINCT owner_id FROM heart_rate`, then drop `WHERE owner_id = '$owner'` into each panel query).

You can also point Grafana at the Prometheus `/metrics` endpoint for ingest observability — for example, rows ingested per second broken down by metric:

```promql
sum by (metric) (rate(hdh_ingest_rows_total[5m]))
```

For everyday "what changed against my baseline" reading, prefer the [Observatory web app](observatory-web.md); use Grafana when you want full control over the charts. See the project [`README.md`](../../README.md) for the metric tables and the derived continuous-aggregate views.
