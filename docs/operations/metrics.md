# Metrics

The Observatory exposes runtime counters and a latency histogram at `/metrics` in Prometheus text exposition format, so you can monitor ingest throughput and briefing outcomes from your own Prometheus + Grafana setup.

The endpoint is DB-independent: it does not touch Postgres, so it returns `200` even when the database is down — safe to use as a liveness target.

> **The `/metrics` endpoint is unauthenticated by design** so scrapers don't need an `X-API-Key` on a private network. If you expose it beyond your LAN, protect it behind your [reverse proxy](reverse-proxy.md) — do not publish it to the internet.

> Metric names retain the `hdh_` prefix for backward compatibility with existing scrape configs and dashboards.

## Exposed metrics

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `hdh_ingest_batches_total` | counter | `metric` | Batches accepted by `/api/apple/batch`, including empty ones |
| `hdh_ingest_rows_total` | counter | `metric` | Rows persisted per metric (cumulative) |
| `hdh_ingest_duration_seconds` | histogram | `metric` | End-to-end batch handler latency |
| `hdh_ai_briefing_runs_total` | counter | `job`, `result` | Daily briefing / anomaly check / trend analysis runs by outcome (`success` / `failure`) |

## Scrape config

```yaml
scrape_configs:
  - job_name: healthsave-observatory
    metrics_path: /metrics
    static_configs:
      - targets: ['api:8000']  # or 'localhost:8000' for host scrape
```

## Sample PromQL

Rows ingested per second, broken down by metric (a Grafana time-series panel):

```promql
sum by (metric) (rate(hdh_ingest_rows_total[5m]))
```

Pair this with an alert on briefing failures so you get a heads-up when nightly analysis starts failing:

```promql
rate(hdh_ai_briefing_runs_total{result="failure"}[1h])
```

## See also

- [Reverse proxy](reverse-proxy.md) — protecting the unauthenticated endpoint if exposed
- [Troubleshooting](troubleshooting.md) — diagnosing failing briefings
