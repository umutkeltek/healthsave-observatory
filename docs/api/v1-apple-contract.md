# v1 Apple contract (frozen ingest)

The v1 ingest surface is the byte-stable contract that the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app — the live App Store binary — depends on. Three endpoints carry it: a batch ingest, a status read, and a liveness probe. **Their shapes, field names, and response structure are locked.** This page summarizes the contract; [`API.md`](../../API.md) is the authoritative, full-detail version (including the complete HealthKit metric catalog and per-metric table mapping).

> **The one rule: don't change the shapes.** Field names, the flat status response, and the success/empty payloads are part of a published binary's expectations. Never rename, wrap, or restructure them, and never alter the OpenAPI lock for these routes. New client-facing surfaces go under [`/api/v2/`](v2-read-api.md) instead. This is machine-enforced — the contract tests go red if a v1 shape drifts.

## `POST /api/apple/batch`

Receives one HealthKit metric batch (the app chunks each metric into batches). Keyed when `API_KEY` is set.

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

**Response** (`processed` or `empty`)

```json
{ "status": "processed", "metric": "heart_rate", "batch": 0, "total_batches": 1, "records": 1 }
```

Dedicated first-class tables: `heart_rate`, `hrv`, `blood_oxygen`, `body_temperature`, `sleep_sessions`, `workouts`, `daily_activity`. Everything else lands in `quantity_samples`. Every raw batch is written to `raw_ingestion_log` before processing, giving a replay/audit trail without changing the response shape. Ingestion is idempotent — re-syncing or retrying never inflates your data.

The endpoint accepts **any** metric name. The full HealthKit catalog (120+ metrics), the dedicated-table and daily-activity mappings, category-event formats, and the workout payload shape are documented in [`API.md`](../../API.md).

## `GET /api/apple/status`

Returns per-table record counts and date ranges so the app and operators can confirm a sync landed. Keyed when `API_KEY` is set.

The response is a **flat** object: each top-level key is a metric/table, and the iOS app parses it directly.

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

Do **not** wrap this as `{"status":"ok","counts":{...}}`. The flat shape is the contract; the iOS status UI reads top-level keys.

## `GET /api/health`

App-friendly liveness probe. Returns a minimal `2xx` response:

```json
{ "status": "ok" }
```

The HealthSave app (1.5+) calls `GET /api/health` first and falls back to `GET /health` on a `404`, so implement either or both. The `status` value is matched case-insensitively against an accept-list (`ok`, `healthy`, `alive`, `ready`, `up`); a `401`/`403` here is read as an auth problem, not a "wrong server" problem. The exact tolerances are pinned in `API.md`.

## Building a compatible backend

A HealthSave-compatible server does **not** have to be this one. The minimum core contract is: `GET /api/health` returns `2xx`, `GET /api/apple/status` returns flat metric objects, and `POST /api/apple/batch` accepts batches with a `2xx`. Idempotent batch handling is strongly recommended. Optional Data Hub extensions (`/api/v2/sync/*` receipts) light up extra confidence tiers in the app when present — a v1-only server still syncs cleanly without them.

The full contract, compatibility tiers, and the iOS liveness behavior live in [`API.md`](../../API.md). For payload-level examples across both surfaces, see [`API_REFERENCE.md`](../../API_REFERENCE.md). To register your backend in the community list, see [Storage backends](../development/storage-backends.md) and open a PR ([`CONTRIBUTING.md`](../../CONTRIBUTING.md)).
