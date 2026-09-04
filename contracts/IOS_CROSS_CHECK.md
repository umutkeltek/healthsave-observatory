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

> **Source of truth: `contracts/ios-headers.json`** (machine-pinned;
> the table below is commentary). The manifest is enforced three ways:
> `tests/contract/api_v1/test_v1_ios_headers.py` (server consumes every
> header + manifest completeness against the ingest source),
> `ios_app/Tests/HealthSyncTests/HeaderContractTests.swift` (the app's
> real upload request emits exactly the manifest set), and
> `tests/contract/test_ios_headers_in_sync.py` (the iOS mirror is
> byte-equal).

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

---

# v2 Apple Batch Wire — `POST /api/v2/apple/batch` (Plan 2026-09-03)

> **Scope.** The v1 wire above is **FROZEN — do not edit** (CLAUDE.md Law 5;
> the shipped App Store binary parses it byte-exact). This section describes
> the additive v2 wire; the v1 route stays alive for shipped clients until
> the next App Store release stabilizes v2.

The v2 wire was introduced in response to Eric Lorenzo Benjamin Jr.'s feedback
thread (a downstream operator running our wire into a longitudinal engine).
It addresses four blockers and two soft asks against v1:

| # | Blocker | v2 fix |
|---|---|---|
| 1 | No `startDate`+`endDate` per sample (RHR interval identity lost) | Both fields required on every sample |
| 2 | `HKAnchoredObjectQuery` delivers `[HKDeletedObject]`; iOS threw them away | Top-level `deletions: [{uuid, deletedAt}]` array |
| 3 | No `unit` field (server guessed, silently corrupted) | Per-sample `unit` (UCUM/`HKUnit.unitString`) |
| 4 | No local UTC offset (sleep day-bucketing + DST travelers broke) | Per-sample `tzOffsetMinutes` |
| + | Strongly wanted: HR motion context, sample UUID for idempotent identity | `motionContext` on HR; `uuid` on every quantity/category/workout/ECG |

Out of scope (separate work): HRV beat-to-beat (`HKHeartbeatSeries`) — different
HealthKit query and canonical value type; tracked as a follow-up.

## v2 endpoint

| iOS endpoint | iOS file:line | Server route |
|--------------|---------------|--------------|
| `/api/v2/apple/batch` | `Config.swift` (Slice 4: `v2BatchEndpoint`) | `POST /api/v2/apple/batch` |

The v2 route is **additive at the URL layer** — no existing client is
redirected; the iOS app picks v1 vs v2 based on a build flag and falls back to
v1 if the server returns 404/405 on the v2 route (`SyncEngine` slice-4 logic).

## v2 request body

```json
{
  "schema_version": 2,
  "metric": "heart_rate",
  "batch_index": 0,
  "total_batches": 1,
  "source_bundle_id": "com.healthsave.ios",
  "device": { "name": "Apple Watch", "model": "Watch7,2" },
  "samples": [
    {
      "uuid": "D2C7…-0000-4000-8000-000000000001",
      "startDate": "2026-08-30T07:14:00-04:00",
      "endDate":   "2026-08-30T07:14:00-04:00",
      "qty": 52,
      "unit": "count/min",
      "tzOffsetMinutes": -240,
      "motionContext": "sedentary",
      "source": "Apple Watch"
    }
  ],
  "deletions": [
    { "uuid": "D2C7…-0000-4000-8000-00000000007A", "deletedAt": "2026-08-31T03:14:00Z" }
  ]
}
```

### v2 sample-key set (pinned by `tests/contract/api_v2/test_v2_apple_batch_contract.py`)

| Key | Type | Required | Notes |
|---|---|---|---|
| `uuid` | UUID string | required (quantity/category/workout/ECG); optional for medication | Stable identity for the sample's lifetime |
| `startDate` | ISO-8601 with offset | required | Replaces v1's `date`/`start`; server accepts `start`/`startDate`/legacy `date` for migration window |
| `endDate` | ISO-8601 with offset | required for intervals; same as `startDate` for instantaneous | Server falls back to `startDate` if missing on a quantity sample |
| `qty` | number | required (quantity) | Same as v1 |
| `unit` | UCUM/`HKUnit.unitString` | required | Per-sample; server validates against the metric's allowed-units list; unknown unit → **422** (deterministic, frozen-client-safe) |
| `tzOffsetMinutes` | int (-1440…+1440) | optional | Server stamps the offset on the raw payload + the canonical row's provenance |
| `motionContext` | enum string | optional, HR only | `sedentary` / `active` / `notSet`; omitted means "not present on the sample" |
| `source` | string | required | Same as v1 |

### v2 top-level keys

| Key | Required | Notes |
|---|---|---|
| `schema_version` | optional (default `1`) | v2 route rejects anything ≠ 2 |
| `deletions` | optional | `[{uuid, deletedAt}]`; marked `superseded` on `canonical_observations` + (if present) on v1 dedicated tables |
| `device` | optional | Free-form `{name, model}` |
| `source_bundle_id` | optional | iOS sends `com.healthsave.ios` |

## v2 request headers

> **Source of truth: `contracts/v2-ios-headers.json`** (machine-pinned; the
> table below is commentary). The v2 manifest is **additive over the v1
> manifest** — every v1 header is preserved, and one advisory header is
> added: `X-HealthSave-Schema-Version: 2`. The body's `schema_version=2` is
> the source of truth for the wire version; the header is advisory only.

The v2 manifest is enforced three ways:

1. `tests/contract/api_v2/test_v2_ios_headers.py` — server consumes every header + completeness.
2. `V2HeaderContractTests.swift` (iOS) — the app emits exactly these.
3. `tests/contract/test_ios_v2_headers_in_sync.py` — byte-equal mirror invariant.

## v2 response shape

Identical to v1 (`_delivery_receipt_response` in `server/api/ingest.py`).
No client-visible shape change. The v2 route reuses the same builder.

## Cross-check is enforced by

1. `tests/contract/api_v2/test_v2_apple_batch_contract.py` — happy path, missing uuid, unknown unit, malformed tz, schema_version=1 (rejected), idempotency replay, deletion supersedes canonical, deletion supersedes v1 dedicated rows.
2. `tests/contract/test_ios_v2_corpus_in_sync.py` — iOS v2 batch payloads are byte-mirrored at `tests/fixtures/apple_healthsave_v2/`.
3. `tests/contract/test_ios_v2_headers_in_sync.py` — byte-equal mirror invariant on the header manifest.
4. `V2HeaderContractTests.swift` (iOS) — the app's real upload request emits exactly the v2 manifest.

## Migration ownership (Slice 1)

Migration `db/migrations/025_apple_source_uuid_and_superseded.sql` adds
nullable `source_uuid UUID` + `status TEXT NOT NULL DEFAULT 'active'`
(check `status IN ('active','superseded')`) to `heart_rate`, `hrv`,
`blood_oxygen`, `body_temperature`, `sleep_sessions` — additive only
(CLAUDE.md Law 5). Partial unique index `WHERE source_uuid IS NOT NULL`
plus partial active-index. The conflict clause becomes a two-arm
`(owner_id, source_uuid, time) WHERE source_uuid IS NOT NULL` /
`(time, device_id, owner_id)`. (The dedicated
tables are hypertables, so the partition column `time` is part of the
identity arbiter.)

## Android adoption

Tracked in `Plans/2026-09-03-v2-apple-ingest-wire.md` Slice 8 — deferred
until iOS ships v2 stable from the App Store. Single-platform risk first.
