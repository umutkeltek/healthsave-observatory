# Grafana Dashboards

Grafana is the bundled power-user dashboard surface for HealthSave Observatory. It is not the product identity and it is not the normal first-run experience; [Observatory web](observatory-web.md) is the primary insight-first surface.

Use Grafana when you want raw charting, SQL-backed exploration, custom panels, or homelab dashboards.

See [Web vs Grafana](web-vs-grafana.md) for the separation.

## What Is Bundled

Fresh installs auto-provision:

- `deploy/grafana/provisioning/datasources/healthsave.yaml` - TimescaleDB datasource
- `deploy/grafana/provisioning/dashboards/default.yaml` - provisioning manifest
- `deploy/grafana/dashboards/` - dashboard JSON files

Grafana runs on:

```text
http://localhost:3000
```

Default login:

- user: `admin`
- password: `GRAFANA_PASSWORD` from `.env`

Grafana binds `127.0.0.1` by default. To reach it from another LAN device, deliberately set:

```bash
GRAFANA_BIND=0.0.0.0
```

Do not expose Grafana directly to the internet over plain HTTP.

## Supported Dashboards

Dashboards load automatically:

| Dashboard | File | Depends On | Notes |
|---|---|---|---|
| HealthSave Overview | `deploy/grafana/dashboards/healthsave-overview.json` | `heart_rate`, `hrv`, `blood_oxygen`, `daily_activity`, `sleep_sessions`, `workouts` | Best first dashboard |
| Activity & Movement | `deploy/grafana/dashboards/activity.json` | `daily_activity`, `quantity_samples` | Activity and movement panels |
| Heart & Cardiovascular | `deploy/grafana/dashboards/heart.json` | `heart_rate`, `hrv`, cardiovascular streams | Heart, HRV, resting-rate panels |
| Sleep Analysis | `deploy/grafana/dashboards/sleep.json` | `sleep_sessions`, sleep-related streams | Sleep duration and sleep-stage panels |
| Cross-Device Insights | `deploy/grafana/dashboards/insights.json` | canonical source/device/stream tables | Source comparison and data-quality panels |
| Workouts | `deploy/grafana/dashboards/workouts.json` | `workouts`, activity streams | Workout volume and session panels |

Grafana reads the canonical TimescaleDB schema directly. Any panel you can express in SQL can work.

For multi-person households, add an `owner_id` dashboard variable and filter panel queries by owner.

## Metrics

Grafana can also point at Prometheus metrics from the API/worker. Example: rows ingested per second by metric:

```promql
sum by (metric) (rate(hdh_ingest_rows_total[5m]))
```

## Rule Of Thumb

Use Observatory web for everyday "what changed compared with my baseline?" reading.

Use Grafana when you want full control over charts, SQL, and debugging panels.
