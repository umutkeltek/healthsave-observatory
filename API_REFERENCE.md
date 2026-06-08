# API Reference — payload-level contract

Every HTTP endpoint: **what it returns, the request/response payload, when it's called, and by whom.** This is the human-readable companion to the machine-readable OpenAPI lock (`contracts/openapi/v1.locked.json`) and the frozen-v1 prose in [`API.md`](API.md). Examples use **synthetic values** (no real health data).

> Two directions, never conflated:
> - **INGEST (inbound, FROZEN):** the HealthSave iOS app → `/api/apple/*`. Shapes are byte-stable; never change them.
> - **READ (outbound, evolvable):** dashboards / Home Assistant / integrators → `/api/v2/*` (+ frozen `/api/insights/*`).

## Conventions

- **Base URL:** `http://<host>:8000` (local) / `http://<host>:18080` (reference VM deploy). The iOS app is given the base URL and appends the path.
- **Timestamps:** ISO 8601 UTC with a trailing `Z` (e.g. `2026-06-08T20:17:39Z`). Naive timestamps are assumed UTC.
- **Content type:** `application/json` for request and response bodies.
- **IDs:** canonical metric ids are dotted (`vital.heart_rate`, `sleep.stage`); run/stream ids are UUIDs.

## Authentication

Auth is a single shared key sent as the **`X-API-Key`** header.

| Server state | Keyed endpoint behavior |
|---|---|
| `API_KEY` set (production) | missing/wrong key → **`401`**; correct key → `200` |
| `API_KEY` unset **and** `ALLOW_NO_AUTH=true` (local demo) | served open |
| `API_KEY` unset **and not** acknowledged | **`503 auth_not_configured`** (SECURITY-001 default-deny) |

**Open** (no key): `/health`, `/api/health`, `/ready`, `/metrics`, `/api/v2/meta`, `/api/v2/setup/diagnostics`, `/api/v2/metrics` (static catalog only — no health data).
**Keyed** (`401` without key): everything else, i.e. all endpoints that return health data.

---

## 1. Health & ops — open

| Endpoint | Who calls it | Returns |
|---|---|---|
| `GET /health` | orchestrator/Docker healthcheck | process liveness |
| `GET /api/health` | iOS app liveness probe (1.5+), monitors | app-friendly liveness |
| `GET /ready` | orchestrator, deploy verify | API **+ DB** readiness |
| `GET /metrics` | Prometheus | text exposition (not JSON) |

```jsonc
// GET /api/health
{ "status": "ok" }
// GET /ready
{ "status": "ready", "database": "ok" }
```

---

## 2. Ingest — v1 (FROZEN) · caller: HealthSave iOS app

### `POST /api/apple/batch` — keyed
One HealthKit metric batch (the app chunks each metric into batches). Full metric catalog + dedicated-table mapping in [`API.md`](API.md).

**Request**
```json
{
  "metric": "heart_rate",
  "batch_index": 0,
  "total_batches": 1,
  "samples": [
    { "date": "2026-06-08T20:17:39Z", "qty": 62, "unit": "count/min", "source": "Apple Watch" }
  ]
}
```
**Response** (`processed` | `empty`)
```json
{ "status": "processed", "metric": "heart_rate", "batch": 0, "total_batches": 1, "records": 1 }
```
- Dedicated tables: `heart_rate, hrv, blood_oxygen, body_temperature, sleep_sessions, workouts, daily_activity`; everything else → `quantity_samples`. Every raw batch is logged to `raw_ingestion_log` before processing (replay trail).

### `GET /api/apple/status` — keyed
Per-table record counts + date ranges. The app + operators use it to confirm sync. **Flat shape** (top-level table keys — the iOS app parses this directly; do not wrap it).
```json
{
  "heart_rate":       { "count": 2964878, "oldest": "2024-08-01T00:00:00Z", "newest": "2026-06-08T20:17:39Z" },
  "hrv":              { "count": 13557,   "oldest": "...", "newest": "..." },
  "blood_oxygen":     { "count": 79273,   "oldest": "...", "newest": "..." },
  "daily_activity":   { "count": 3428,    "oldest": "...", "newest": "2026-06-07" },
  "sleep_sessions":   { "count": 2562,    "oldest": "...", "newest": "..." },
  "workouts":         { "count": 592,     "oldest": "...", "newest": "..." },
  "quantity_samples": { "count": 229114,  "oldest": "...", "newest": "..." }
}
```

---

## 3. Read — v2 (evolvable) · callers: dashboard (apps/web), Home Assistant bridge, integrators, operator

### `GET /api/v2/meta` — open
Version axes of the running backend (for clients to detect contract/ontology drift).
```json
{ "v2_status": "active",
  "versions": { "api_contract": "1", "ontology": "1", "normalizer": "1", "fusion_policy": "1" },
  "decision_record": "ADR-0001" }
```

### `GET /api/v2/metrics` — open (catalog only)
The static metric catalog (no values → safe to expose).
```json
[ { "id": "vital.heart_rate", "display_name": "Heart Rate", "category": "vital",
    "value_type": "quantity", "canonical_unit": "count/min" } ]
```

### `GET /api/v2/metrics/{metric_id}/series` — keyed
Time series for one canonical metric. **Query:** `range` (e.g. `7d`) or `start`/`end` (ISO). The dashboard reads this; the local LLM narrator is designed to consume the same contract.
```json
{ "metric": { "id": "vital.heart_rate", "display_name": "Heart Rate", "category": "vital",
              "value_type": "quantity", "canonical_unit": "count/min" },
  "range": "7d", "start": "2026-06-01T00:00:00Z", "end": "2026-06-08T00:00:00Z",
  "points": [ { "t": "2026-06-08T20:17:39Z", "value": 62.0, "code": null,
                "unit": "count/min", "source_id": "apple_watch", "confidence": null } ] }
```

### `GET /api/v2/privacy` — keyed
The egress trust-boundary posture (the moat, made inspectable).
```json
{ "provider": "ollama", "destination": "local", "is_local": true,
  "allow_cloud_egress": false, "cloud_active": false, "cloud_prompt_redaction": true,
  "raw_observations_leave_host": false,
  "egress": [ { "payload_class": "RAW_OBSERVATIONS", "allowed": false, "leaves_host": false,
                "reason": "raw rows never cross the host boundary" } ] }
```

### `GET /api/v2/readiness` — keyed
Per-metric data sufficiency (is there enough history to run anomaly/trend analysis). Drives the dashboard "what can I analyze yet" view.
```json
{ "as_of": "2026-06-08T20:00:00Z", "last_observation_at": "...", "last_ingested_at": "...",
  "sources": [ { "source_plugin_id": "apple_healthkit", "observation_count": 123456, "last_ingested_at": "..." } ],
  "metrics": [ { "metric_id": "vital.heart_rate", "display_name": "Heart Rate", "category": "vital",
    "observation_count": 2964878, "days_with_data": 280,
    "first_observation_at": "...", "last_observation_at": "...",
    "analyzable": { "anomaly_detection": { "is_sufficient": true, "missing": null, "days_until_sufficient": 0 },
                    "trend_analysis":   { "is_sufficient": true, "missing": null, "days_until_sufficient": 0 } } } ],
  "summary": { "metrics_with_data": 12 } }
```

### `GET /api/v2/setup/diagnostics` — open
Self-describing setup helper (endpoint map + whether auth is required). Used by the iOS setup flow to validate a server URL/port.
```json
{ "service": "health-data-hub", "kind": "datahub", "status": "ok", "auth_required": true,
  "health_endpoint": "/api/health", "status_endpoint": "/api/apple/status",
  "ingest_endpoint": "/api/apple/batch", "latest_sync_endpoint": "/api/v2/sync/runs/latest",
  "coverage_endpoint": "/api/v2/sync/coverage", "anomalies_endpoint": "/api/v2/sync/anomalies",
  "grafana_required": false, "wrong_port_hint": "..." }
```

### `GET /api/v2/export` · `GET /api/v2/export/metrics` — keyed
Bulk export. `export/metrics` lists exportable metrics + counts/ranges; `export` streams rows. **Query:** `limit` (clamped to 100k), metric/time filters.
```json
// GET /api/v2/export/metrics
[ { "metric": "vital.heart_rate", "display_name": "Heart Rate", "count": 2964878,
    "oldest": "...", "newest": "..." } ]
```

### Sync verification — keyed
The "honest accounting" surface: how much the app sent vs what was accepted/inserted/deduped.

- `GET /api/v2/sync/coverage` — per-metric received/accepted/inserted/deduped + destination row counts.
- `GET /api/v2/sync/runs/latest` — the most recent sync run summary.
- `GET /api/v2/sync/runs/{sync_run_id}` — one run, with per-metric breakdown + verification level.
- `GET /api/v2/sync/anomalies` — overlapping/concurrent-run detection.

```json
// GET /api/v2/sync/runs/latest
{ "sync_run_id": "4d8b…", "started_at": "...", "completed_at": "...", "status": "ok",
  "batches_seen": 42, "batches_processed": 42, "batches_empty": 0, "batches_failed": 0,
  "records_received": 5120, "records_accepted": 5120,
  "records_inserted_new": 1903, "records_deduped_existing": 3217, "records_skipped": 0,
  "metrics": ["vital.heart_rate", "vital.hrv"],
  "sample_window": { "min_sample_time": "...", "max_sample_time": "..." },
  "latest_sample_time": "2026-06-08T20:17:39Z" }
```
```json
// GET /api/v2/sync/coverage  (summary + per-metric[])
{ "status": "ok",
  "summary": { "metrics_seen": 12, "batches_seen": 42, "records_received": 5120,
               "records_accepted": 5120, "records_inserted_new": 1903,
               "records_deduped_existing": 3217, "records_skipped": 0 },
  "metrics": [ { "metric": "vital.heart_rate", "batches_seen": 8, "records_received": 1900,
                 "records_inserted_new": 900, "records_deduped_existing": 1000,
                 "storage_result_level": "ok", "newest_receipt_at": "...",
                 "receipt_sample_window": { "min_sample_time": "...", "max_sample_time": "..." },
                 "destination_row_count": 2964878 } ] }
```

### AI insights (v2) — keyed
- `GET /api/v2/insights/latest` — current daily briefing + weekly summary (`null` until generated).
- `GET /api/v2/insights/findings` — structured findings from the statistical engine (the analyst's evidence).
- `GET /api/v2/insights/correlations` — discovered metric correlations.
- `POST /api/v2/insights/trigger` — request a run. **Body:** `{ "type": "daily" | "weekly" | "anomaly" | ... }`.

```json
// GET /api/v2/insights/findings
{ "findings": [ { "id": 1, "finding_type": "recovery_score", "metric": "recovery", "severity": "info",
    "structured_data": { "score": 71, "method": "v1",
      "contributors": { "sleep_efficiency": 0.92, "hrv_vs_baseline_pct": 4.0,
                        "rhr_vs_baseline_pct": -2.0, "temperature_deviation_c": 0.1,
                        "respiratory_rate_vs_baseline_pct": 0.0 },
      "missing_inputs": [], "signals_available": ["hrv", "rhr", "sleep"] },
    "created_at": "2026-06-08T07:05:00Z" } ],
  "count": 1 }
```

---

## 4. Insights — v1 (FROZEN, keyed) · caller: iOS app + legacy clients

Typed responses (schemas in the OpenAPI lock):
- `GET /api/insights/latest` → `InsightsLatestResponse` (example below)
- `GET /api/insights/daily` → `DailyBriefingResponse`
- `GET /api/insights/weekly` → `WeeklySummaryResponse`
- `GET /api/insights/anomalies` → `AnomaliesListResponse`
- `GET /api/insights/trends` → `TrendsListResponse`
- `GET /api/insights/runs` → `RunsListResponse`
- `POST /api/insights/trigger` → `TriggerResponse`

```json
// GET /api/insights/latest -> InsightsLatestResponse
{ "daily_briefing": { "id": 10, "date": "2026-06-08", "narrative": "…",
      "findings": [ { "id": 1, "finding_type": "anomaly", "metric": "vital.hrv",
                      "severity": "warn", "structured_data": {}, "created_at": "…" } ],
      "created_at": "…" },
  "weekly_summary": { "id": 3, "week_start": "2026-06-01", "week_end": "2026-06-07",
                      "narrative": "…", "findings": [], "created_at": "…" },
  "recent_findings": [] }
```
```json
// GET /api/insights/trends -> TrendsListResponse
{ "count": 1, "trends": [ { "metric": "vital.resting_heart_rate", "direction": "down",
    "slope": -0.3, "p_value": 0.02, "confidence": "high", "period_days": 30 } ] }
// POST /api/insights/trigger  body {"type":"daily"} -> TriggerResponse
{ "status": "queued", "run_id": 41, "run_type": "daily", "message": null }
```
Other typed shapes: `AnomaliesListResponse {count, anomalies[{id,metric,severity,direction,magnitude,detected_at,context}]}`, `DailyBriefingResponse`, `WeeklySummaryResponse`, `RunsListResponse {count, runs[{id,job_kind,status,attempt,started_at,ended_at,error,triggered_by}]}`.

---

## 5. Experiments & agents — v2 (keyed) · caller: dashboard / power users

**Experiments** (n-of-1 self-experiments):
- `GET /api/v2/experiments` → `{count, experiments[ExperimentView]}`
- `POST /api/v2/experiments` — body `CreateExperimentRequest {lever_metric_id*, outcome_metric_id*, hypothesis, design, block_days, start_date}`
- `GET /api/v2/experiments/candidates` → `{candidates, count, testable_count}`
- `GET /api/v2/experiments/{experiment_id}` · `POST /api/v2/experiments/{experiment_id}/abandon` · `POST /api/v2/experiments/{experiment_id}/analyze` → `ExperimentView`

```json
// ExperimentView (abridged)
{ "id": "exp_…", "status": "running", "hypothesis": "…", "design": "AB",
  "lever": "Caffeine", "lever_metric_id": "intake.caffeine_mg",
  "outcome": "Sleep efficiency", "outcome_metric_id": "sleep.efficiency",
  "block_days": 7, "start_date": "2026-06-01", "created_at": "…",
  "calendar": [ { "index": 0, "label": "A", "start": "…", "end": "…" } ],
  "progress": { "day_index": 4, "total_days": 14, "days_remaining": 10, "pct": 28.5,
                "current_phase": "A", "is_complete": false },
  "results": {} }
```

**Agents** (proposed actions awaiting a human decision):
- `GET /api/v2/agents/proposals` → `{count, undecided_only, proposals[ProposalView]}`
- `POST /api/v2/agents/proposals/{proposal_id}/decide` — body `DecideRequest {decision*, rationale}` → `DecideResponse {proposal_id, decision, decided_by, decision_id}`

---

## 6. Webhooks

### `POST /api/v2/sources/whoop/webhook` · caller: Whoop
Inbound Whoop events. Verifies `base64(HMAC-SHA256(secret, ts + raw_body))` against `X-WHOOP-Signature` (constant-time). Unset secret → warn + allow (unconfigured no-op).

---

## 7. Coming in R2 — identity (Source / Device / Stream)

New **typed** read endpoints (this is the half currently missing). Once built they appear here with full schemas:
- `GET /api/v2/sources` — integrations data entered through (apple-healthkit-ios, whoop-oauth, …)
- `GET /api/v2/devices` — physical emitters (Apple Watch, Whoop band, …)
- `GET /api/v2/streams` · `GET /api/v2/streams/{stream_id}` — the join (device-via-integration), with **stable UUIDs** that Home Assistant keys on.

---

## Who calls what (quick matrix)

| Caller | Endpoints |
|---|---|
| **HealthSave iOS app** | `POST /api/apple/batch`, `GET /api/apple/status`, `GET /api/health`, `GET /api/v2/setup/diagnostics`, `GET /api/v2/sync/*`, `GET /api/insights/*` |
| **Home Assistant bridge** (`homeassistant_mqtt`) | **Does not call the API** — reads the DB directly via a storage repository and publishes to MQTT. (R3: will key HA entities on canonical stream UUIDs.) |
| **Dashboard (apps/web "Private Observatory")** | `GET /api/v2/{meta,metrics,metrics/{id}/series,readiness,privacy,insights/*,sync/*,experiments,agents/proposals}` |
| **Grafana** | direct DB (not the API) |
| **Worker / scheduler** | internal (writes findings consumed via `/api/v2/insights/*`) |
| **Operator** | `GET /ready`, `GET /api/v2/setup/diagnostics`, `GET /api/v2/sync/coverage`, `GET /metrics` |
| **Whoop** | `POST /api/v2/sources/whoop/webhook` |
