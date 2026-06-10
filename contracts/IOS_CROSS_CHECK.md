# iOS Cross-Check — HealthSave Wire ↔ Server v1

The `contracts/openapi/v1.locked.json` file is a snapshot of what the
FastAPI server *thinks* the contract is (derived from Pydantic models
via `app.openapi()`). That is necessary but not sufficient — it would
silently lie if the iOS app sent or expected something different.

This file records the cross-check between the live HealthSave iOS app
and the server's v1 surface, performed at the Phase 0 freeze. Re-run
the cross-check whenever the iOS networking layer changes.

> **Source of truth.** iOS networking lives in
> the sibling `../ios_app/Sources/HealthSync/` repository in the HealthSave
> product workspace.
> Cross-check with that repo at every contract bump.

## Endpoints iOS actually calls (5: 3 v1 + 2 v2)

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
| `/api/v2/sync/runs/latest` | `Config.swift:49` | `GET /api/v2/sync/runs/latest` |
| `/api/v2/sync/runs/{id}` | `Config.swift:51` | `GET /api/v2/sync/runs/{sync_run_id}` |

**The two v2 routes live at a v2 location but carry v1-grade freeze
semantics.** The shipped binary hardcodes both paths in `Config.swift`
(it does not discover them from `/api/v2/setup/diagnostics`) and
decodes the responses in
`BackendCompatibility.swift::decodeLatestReceipt` for destination
receipts. "v2 is free to evolve" does NOT apply to them.

The "iOS-narrow" v1 contract is enforced by
`tests/contract/api_v1/test_v1_ios_contract.py`; the iOS-load-bearing
v2 surface (routes, response keys, the `"empty"` status sentinel, and
`/latest`-before-`/{sync_run_id}` route ordering) is enforced by
`tests/contract/test_ios_v2_surface.py`. A removal or reshape of any of
these five is an iOS-app-breaking change and must be coordinated with
an App Store release.

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
| `Idempotency-Key` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.idempotency_key`) |
| `X-HealthSave-Sync-Run-ID` | `SyncReliability.swift:456` | yes (`healthsave_sync_receipts.sync_run_id`) |
| `X-HealthSave-Batch-ID` | `SyncReliability.swift:457` | yes (`healthsave_sync_receipts.batch_id`) |
| `X-HealthSave-Payload-Hash` | `SyncReliability.swift:458` | yes (`healthsave_sync_receipts.payload_hash`) |
| `X-HealthSave-Metric` | `SyncReliability.swift:459` | yes (`healthsave_sync_receipts.metric`) |
| `X-HealthSave-Batch-Index` | `SyncReliability.swift:460` | yes (`healthsave_sync_receipts.batch_index`) |
| `X-HealthSave-Total-Batches` | `SyncReliability.swift:461` | yes (`healthsave_sync_receipts.total_batches`) |
| `X-HealthSave-Sync-Mode` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.sync_mode`) |
| `X-HealthSave-Anchor-Present` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.anchor_present`) |
| `X-HealthSave-Lower-Bound-Reason` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.lower_bound_reason`) |
| `X-HealthSave-Full-Export` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.full_export`) |
| `X-HealthSave-Query-Lower-Bound` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.query_lower_bound_at`) |
| `X-HealthSave-Sample-Min-Time` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.sample_min_at`) |
| `X-HealthSave-Sample-Max-Time` | `SyncReliability.swift` | yes (`healthsave_sync_receipts.sample_max_at`) |

**iOS does NOT send:**

- `X-User-Id` — the multi-user header. The server falls back to a
  sentinel UUID when absent (`server/ingestion/owner.py:13`). The
  v1.x contract is single-user-by-default. Multi-user iOS coordination
  is a v2 concern.

**Verdict:** match. The `X-HealthSave-*` headers are part of the iOS
wire iOS produces; the server records them as delivery receipts for
operator proof, support diagnostics, degraded-recovery analysis, and
duplicate-safe retry analysis.
The batch response includes additive receipt fields such as `receipt_id`,
`sync_run_id`, `idempotency_key`, `records_received`, `records_accepted`,
nullable `records_inserted_new` / `records_deduped_existing`,
`storage_result_level`, `sample_window`, `latest_sample_time`, and
`verification_level: "delivery_receipt"` while preserving the legacy v1
`status/inserted/skipped` response fields.

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

**iOS:** calls the endpoint, parses the JSON body and accepts the
response when `status` matches the iOS-side healthy-value accept-list
(see "Liveness probe acceptance" below). Used as a liveness probe in
the destination-setup assistant.

**Server:** returns `{"status": "ok"}`. The reference Data Hub value
is `"ok"`; any value in the iOS accept-list is acceptable for a
generic compatible backend.

**Verdict:** match. The reference Data Hub satisfies the iOS check
exactly; alternative backends have a tolerant window (next section).

## Liveness probe acceptance (iOS-side semantics, build 1.5+)

The iOS liveness probe is intentionally tolerant of generic compatible
servers. The contract a third-party backend has to satisfy is wider
than the reference Data Hub's exact response. Source of truth:
`ios_app/Sources/HealthSync/BackendCompatibility.swift`.

**Endpoint discovery.** iOS calls `/api/health` first. If that returns
`404`, iOS retries once at `/health`. Either path may be the only one
implemented. Both reaching `404` produces the `notHealthsave` verdict.

**Status-value accept-list.** iOS accepts any of the following values
in the response `status` field, case-insensitive, with surrounding
whitespace trimmed:

- `ok` *(reference Data Hub)*
- `healthy`
- `alive`
- `ready`
- `up`

Anything else — including `broken`, `error`, `down`, `fail`,
`starting`, or a missing/non-string `status` field — produces
`notHealthsave`.

**Authentication.** iOS forwards the configured `x-api-key` header on
the liveness request when the user has set one. A `401` or `403`
response on the liveness path is classified as `authFailed` (the user
gets "check your key" copy), not `notHealthsave`. Generic compatible
servers may protect `/api/health` (defense in depth) without breaking
the probe.

**Timeout.** 10 seconds on the liveness request. Matches the contract
probe.

**iOS-side enforcement.** All five behaviors above are pinned by
`Tests/HealthSyncTests/BackendCompatibilityTests.swift`:

- `testLivenessAcceptsCommonHealthyStatusValues` (9 accepted values)
- `testLivenessRejectsExplicitlyBrokenStatusValues` (5 rejected)
- `testLiveness401IsClassifiedAsAuthFailed`
- `testLiveness403IsClassifiedAsAuthFailed`
- `testLivenessSendsAPIKeyWhenConfigured`
- `testLivenessOmitsAPIKeyWhenNotConfigured`
- `testLivenessTreatsWhitespaceAPIKeyAsAbsent`
- `testLivenessFallsBackToShortHealthPath`
- `testLivenessFallbackAcceptsAlternateHealthyStatusValues`
- `testLivenessFallback401IsAuthFailed`
- `testLivenessFallbackSendsAPIKeyWhenConfigured`
- `testLivenessDoesNotProbeFallbackWhenPrimaryIsHealthy`
- `testLiveness404OnBothHealthPathsClassifiesAsNotHealthsave`

## Cross-check is enforced by

1. `tests/contract/api_v1/test_v1_contract.py` — full OpenAPI golden snapshot.
2. `tests/contract/api_v1/test_v1_ios_contract.py` — narrow iOS-frozen subset (3 routes + the four batch-payload field names).
3. `tests/test_api_contract.py::test_status_endpoint_returns_flat_metric_objects` — flat status shape.

Any change to the iOS networking layer that touches an endpoint URL,
a header name, a request payload field, or a response shape requires
a coordinated re-run of this cross-check and a regen of the v1 lock.

## 2026-05-12 OpenAPI lock regen: v2 agent proposals

The OpenAPI lock was regenerated after the Phase 7-E server work added
operator-review endpoints under `/api/v2/agents/proposals` and
`/api/v2/agents/proposals/{proposal_id}/decide`.

**iOS coordination verdict:** no iOS app release required. The HealthSave
iOS app still calls only the three endpoints listed above:

- `POST /api/apple/batch`
- `GET /api/apple/status`
- `GET /api/health`

The regenerated lock adds v2-only schemas/routes to the global FastAPI
OpenAPI snapshot, but does not change the request/response shapes or
auth semantics of the iOS-narrow v1 surface.

## healthsave.app

The marketing site at <https://healthsave.app> is the public landing
page for the iOS app. It does not host an alternative API surface.
The iOS app's *backend* is whatever URL the user configures in-app
(typically a self-hosted `health-data-hub` instance). There is no
HealthSave-hosted server endpoint in the v1 contract.
