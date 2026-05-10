# iOS Cross-Check — HealthSave Wire ↔ Server v1

The `contracts/openapi/v1.locked.json` file is a snapshot of what the
FastAPI server *thinks* the contract is (derived from Pydantic models
via `app.openapi()`). That is necessary but not sufficient — it would
silently lie if the iOS app sent or expected something different.

This file records the cross-check between the live HealthSave iOS app
and the server's v1 surface, performed at the Phase 0 freeze. Re-run
the cross-check whenever the iOS networking layer changes.

> **Source of truth.** iOS networking lives in
> `/Users/umut/Projects/products/healthsave/ios_app/Sources/HealthSync/`.
> Cross-check with that repo at every contract bump.

## Endpoints iOS actually calls (3 of 12)

The iOS app uses a *narrower* surface than the full v1 contract. The
other v1 routes serve other v1 clients (the
[`health-data-to-mqtt`](https://github.com/bietiekay/health-data-to-mqtt)
community bridge, Grafana's PostgreSQL datasource, and web users of
the insights routes).

| iOS endpoint | iOS file:line | Server route |
|--------------|---------------|--------------|
| `/api/apple/batch` | `Config.swift:31` | `POST /api/apple/batch` |
| `/api/apple/status` | `Config.swift:32` | `GET /api/apple/status` |
| `/api/health` | `Config.swift:33` | `GET /api/health` |

The "iOS-narrow" contract is enforced separately by
`tests/contract/api_v1/test_v1_ios_contract.py`. A removal of any of
these three is an iOS-app-breaking change and must be coordinated
with an App Store release.

## `POST /api/apple/batch` — request body

**iOS construction** (`SyncEngine.swift:83-104`, `AppleSyncBatchPayload`):

```swift
struct AppleSyncBatchPayload {
    let metric: String           // → "metric"
    let batchIndex: Int          // → "batch_index"
    let totalBatches: Int        // → "total_batches"
    let samples: [[String: Any]] // → "samples"
}
```

**Server expectation** (`server/models/batch.py`, `BatchPayload`):

```python
class BatchPayload(BaseModel):
    metric: str = "unknown"
    batch_index: int = Field(default=0)
    total_batches: int = Field(default=1)
    samples: list[dict[str, Any]] = Field(default_factory=list)
```

**Verdict:** match. All four field names align byte-exact. The server
treats every field as optional-with-default; the iOS app always sends
all four. The server is therefore tolerant of an older iOS client
that omits a field, while the current iOS client exercises the
strict path.

### Sample dictionary fields

iOS sends per-sample dicts with these keys (varies by metric type, see
`HealthKitExtractor.swift`):

| Key | Type | Used by |
|-----|------|---------|
| `date` | ISO-8601 string | quantity samples (heart_rate, hrv, etc.) |
| `qty` | number | quantity samples |
| `source` | string | every sample (HealthKit source name) |
| `start` | ISO-8601 string | interval samples (workouts, ECG, sleep) |
| `end` | ISO-8601 string | interval samples |

The server accepts `samples: list[dict[str, Any]]` and parses them in
`server/ingestion/parsers.py` and `server/ingestion/handlers.py`. The
sample-key set is part of the v1 contract by construction (changing a
key name on either side breaks ingest).

## `POST /api/apple/batch` — request headers

**iOS sets (`SyncEngine.swift`, `SyncReliability.swift`):**

| Header | Source | Server uses |
|--------|--------|-------------|
| `Content-Type: application/json` | `SyncEngine.swift:1034,1097` | yes (FastAPI body parsing) |
| `x-api-key: <key>` | `SyncEngine.swift:1185` (when `Config.serverAPIKey` set) | yes (`server/api/deps.py:verify_api_key`) |
| `X-HealthSave-Sync-Run-ID` | `SyncReliability.swift:456` | not yet — reserved for future dedup |
| `X-HealthSave-Batch-ID` | `SyncReliability.swift:457` | not yet |
| `X-HealthSave-Payload-Hash` | `SyncReliability.swift:458` | not yet |
| `X-HealthSave-Metric` | `SyncReliability.swift:459` | not yet |
| `X-HealthSave-Batch-Index` | `SyncReliability.swift:460` | not yet |
| `X-HealthSave-Total-Batches` | `SyncReliability.swift:461` | not yet |

**iOS does NOT send:**

- `X-User-Id` — the multi-user header. The server falls back to a
  sentinel UUID when absent (`server/ingestion/owner.py:13`). The
  v1.x contract is single-user-by-default. Multi-user iOS coordination
  is a v2 concern.

**Verdict:** match. The 6 `X-HealthSave-*` headers are part of the iOS
wire iOS produces; the server's tolerance of unknown headers means
they don't currently break anything. They should be considered
*reserved* — if v2 adds dedup-by-hash logic, these headers are
already on the wire and become load-bearing without an iOS release.

## `GET /api/apple/status` — response shape

**iOS decoder** (`ServerSyncView.swift:649`):

```swift
let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
```

iOS treats the response as a free-form `[String: Any]` and walks the
top-level keys, expecting each known metric name to map to an object.

**Server returns** (`server/api/status.py:apple_status`):

```python
{
    "heart_rate":      {"count": 0, "oldest": None, "newest": None},
    "hrv":             {"count": 0, "oldest": None, "newest": None},
    "blood_oxygen":    {"count": 0, "oldest": None, "newest": None},
    "daily_activity":  {"count": 0, "oldest": None, "newest": None},
    "sleep_sessions":  {"count": 0, "oldest": None, "newest": None},
    "workouts":        {"count": 0, "oldest": None, "newest": None},
    "quantity_samples":{"count": 0, "oldest": None, "newest": None},
}
```

**Critical invariant**: top-level keys are metric names directly. There
is no `{"status": "ok", "counts": {...}}` wrapper. Adding a wrapper
breaks the iOS app immediately — see the inline comment at the top
of `server/api/status.py`.

**Verdict:** match. The flat-top-level shape is contracted both in
prose (status.py header comment, project CLAUDE.md "Key Design
Decisions") and in tests (`tests/test_api_contract.py::test_status_endpoint_returns_flat_metric_objects`).

## `GET /api/health` — response shape

**iOS:** calls the endpoint, doesn't decode the body. Used as a
liveness probe in the destination-setup assistant.

**Server:** returns `{"status": "ok"}`.

**Verdict:** match (body is incidental to iOS's use).

## Cross-check is enforced by

1. `tests/contract/api_v1/test_v1_contract.py` — full OpenAPI golden snapshot.
2. `tests/contract/api_v1/test_v1_ios_contract.py` — narrow iOS-frozen subset (3 routes + the four batch-payload field names).
3. `tests/test_api_contract.py::test_status_endpoint_returns_flat_metric_objects` — flat status shape.

Any change to the iOS networking layer that touches an endpoint URL,
a header name, a request payload field, or a response shape requires
a coordinated re-run of this cross-check and a regen of the v1 lock.

## healthsave.app

The marketing site at <https://healthsave.app> is the public landing
page for the iOS app. It does not host an alternative API surface.
The iOS app's *backend* is whatever URL the user configures in-app
(typically a self-hosted `health-data-hub` instance). There is no
hosted-by-Umut server endpoint in the v1 contract.
