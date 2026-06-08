# HealthSave API Contract

> This file is the **frozen v1 ingest contract** (the byte-stable surface the iOS app depends on). For a payload-level reference to **every** endpoint — v1 *and* v2 read/insights/identity, with request/response examples, auth, and who-calls-what — see [`API_REFERENCE.md`](API_REFERENCE.md).

HealthSave expects the server URL to be the base URL only, for example
`https://health.example.com`. The app appends the paths below.

If `API_KEY` is set on the server, protected endpoints require:

```http
x-api-key: your-api-key
```

## Health Checks

### `GET /health`

Returns a minimal process health response.

```json
{
  "status": "ok"
}
```

### `GET /api/health`

Returns the same app-friendly health response.

```json
{
  "status": "ok"
}
```

### `GET /ready`

Checks that the API can reach the database.

```json
{
  "status": "ok",
  "database": "ok"
}
```

## Batch Ingest

### `POST /api/apple/batch`

Receives one HealthKit metric batch.

```json
{
  "metric": "heart_rate",
  "batch_index": 0,
  "total_batches": 1,
  "samples": [
    {
      "date": "2026-04-10T12:00:00Z",
      "qty": 72,
      "unit": "count/min",
      "source": "Apple Watch"
    }
  ]
}
```

Success response:

```json
{
  "status": "processed",
  "metric": "heart_rate",
  "batch": 0,
  "total_batches": 1,
  "records": 1
}
```

The server records the original batch in `raw_ingestion_log` before processing
and marks the raw log row as processed after the batch commit succeeds. This
keeps a replay/debug trail without changing the HealthSave response shape.

Empty batch response:

```json
{
  "status": "empty",
  "metric": "heart_rate",
  "batch": 0,
  "records": 0
}
```

### Dedicated Metrics

These metrics are stored in first-class tables:

| Metric | Table | Notes |
|--------|-------|-------|
| `heart_rate` | `heart_rate` | Beats per minute |
| `heart_rate_variability` | `hrv` | Stored as SDNN milliseconds |
| `blood_oxygen` | `blood_oxygen` | Accepts `97` or `0.97` |
| `oxygen_saturation` | `blood_oxygen` | Alias used by HealthSave |
| `body_temperature` | `body_temperature` | Celsius |
| `wrist_temperature` | `body_temperature` | Alias used by HealthSave |
| `sleep_analysis` | `sleep_sessions` | Aggregates sleep stage samples into sessions |
| `workouts` | `workouts` | Stores workout summaries |
| `activity_summaries` | `daily_activity` | Stores day-level activity summary payloads |

### Daily Activity Quantity Metrics

HealthSave can send these day-level totals as ordinary quantity batches.
The server maps them into `daily_activity` so Grafana dashboards populate
without requiring a separate `activity_summaries` payload.

| Metric | `daily_activity` column |
|--------|--------------------------|
| `step_count` | `steps` |
| `distance_walking_running` | `distance_m` |
| `flights_climbed` | `floors_climbed` |
| `active_energy_burned` | `active_calories` |
| `basal_energy_burned` | `total_calories` |
| `apple_exercise_time` | `active_minutes` |

`apple_stand_time` stays in `quantity_samples` because HealthKit sends it in
minutes, while `daily_activity.stand_hours` is populated from
`activity_summaries.appleStandHours`. `distance_cycling` and
`distance_wheelchair` also stay in `quantity_samples`; the reference schema has
only one `daily_activity.distance_m` column, so mapping multiple sport-specific
distance totals into it would make the stored value depend on batch order.

### Blood Pressure Correlation

When the iOS app sends `"metric": "blood_pressure"`, individual samples may
carry an inner `"metric"` field with the sub-type:

- `blood_pressure_systolic`
- `blood_pressure_diastolic`

The server preserves the inner metric name when storing to `quantity_samples`.

### Device / Source Identity

Each sample's `source`, `source_id`, `sourceName`, `device`, `deviceName`, or
`device_id` field is used as the device identity when present. If no source-like
field is present, the server falls back to `HealthSave`. This prevents samples
from different devices at the same timestamp from overwriting each other.

### ECG

`ecg` batches are accepted for compatibility. HealthSave ECG samples can
include `start`, `end`, `classification`, `numberOfVoltageMeasurements`,
`samplingFrequency`, and `averageHeartRate`. ECG records are not persisted by
this small-footprint server because the current schema has no ECG table.

### Workout Payload Details

Workout samples can include these fields:

```json
{
  "name": "Running",
  "start": "2026-04-10T07:00:00Z",
  "end": "2026-04-10T07:45:00Z",
  "duration": 2700,
  "source": "Apple Watch",
  "activeEnergy": 420,
  "distance": 6500,
  "avgHeartRate": 145,
  "maxHeartRate": 178,
  "heartRateData": [
    {"date": "2026-04-10T07:01:00Z", "qty": 132}
  ],
  "route": [
    {
      "latitude": 41.01,
      "longitude": 28.97,
      "altitude": 42.0,
      "speed": 2.8,
      "timestamp": "2026-04-10T07:01:00Z"
    }
  ]
}
```

The reference server stores the workout summary fields in `workouts`.
`heartRateData` and `route` are accepted as part of the client payload but are
not persisted by this small-footprint server.

### Full HealthKit Metric Catalog

The server accepts any metric name. Below is the complete catalog of metrics
that HealthSave can send. Quantity-like metrics not listed above as dedicated
or daily activity types are stored in `quantity_samples` when each sample has
`date` and `qty` fields.

**Heart & Cardiovascular:**
`heart_rate`, `resting_heart_rate`, `walking_heart_rate_average`,
`heart_rate_variability`, `heart_rate_recovery`,
`atrial_fibrillation_burden`, `vo2_max`, `oxygen_saturation`,
`respiratory_rate`, `peripheral_perfusion_index`

**Blood Pressure & Metabolic:**
`blood_pressure`, `blood_pressure_systolic`, `blood_pressure_diastolic`,
`blood_glucose`, `insulin_delivery`, `blood_alcohol_content`,
`number_of_alcoholic_beverages`

**Activity & Movement:**
`step_count`, `distance_walking_running`, `distance_cycling`,
`distance_swimming`, `distance_wheelchair`,
`distance_downhill_snow_sports`, `distance_cross_country_skiing`,
`distance_paddle_sports`, `distance_rowing`, `distance_skating_sports`,
`flights_climbed`, `swimming_stroke_count`, `push_count`, `nike_fuel`,
`apple_exercise_time`, `apple_stand_time`, `apple_move_time`,
`active_energy_burned`, `basal_energy_burned`, `number_of_times_fallen`

**Walking & Running Dynamics:**
`walking_speed`, `walking_step_length`, `walking_asymmetry`,
`walking_double_support`, `stair_ascent_speed`, `stair_descent_speed`,
`apple_walking_steadiness`, `six_minute_walk_test_distance`,
`running_power`, `running_speed`, `running_stride_length`,
`running_vertical_oscillation`, `running_ground_contact_time`

**Cycling (iOS 17+):**
`cycling_speed`, `cycling_power`, `cycling_cadence`,
`cycling_functional_threshold_power`

**Sport-Specific Speeds (iOS 18+):**
`cross_country_skiing_speed`, `paddle_sports_speed`, `rowing_speed`

**Effort & Exertion:**
`physical_effort`, `workout_effort_score`, `estimated_workout_effort_score`

**Body & Vitals:**
`body_temperature`, `wrist_temperature`, `basal_body_temperature`,
`body_mass`, `body_fat_percentage`, `bmi`, `lean_body_mass`, `height`,
`waist_circumference`, `electrodermal_activity`

**Respiratory:**
`forced_expiratory_volume_1`, `forced_vital_capacity`,
`peak_expiratory_flow_rate`, `inhaler_usage`

**Sleep:**
`sleep_analysis`, `sleeping_breathing_disturbances`

**Environment & Audio:**
`environmental_audio_exposure`, `headphone_audio_exposure`,
`environmental_sound_reduction`, `uv_exposure`, `time_in_daylight`

**Water & Diving:**
`underwater_depth`, `water_temperature`

**Nutrition (38 types):**
`dietary_energy_consumed`, `dietary_protein`, `dietary_fat_total`,
`dietary_fat_saturated`, `dietary_fat_monounsaturated`,
`dietary_fat_polyunsaturated`, `dietary_carbohydrates`, `dietary_sugar`,
`dietary_fiber`, `dietary_cholesterol`, `dietary_sodium`,
`dietary_potassium`, `dietary_calcium`, `dietary_iron`,
`dietary_magnesium`, `dietary_phosphorus`, `dietary_zinc`,
`dietary_manganese`, `dietary_copper`, `dietary_selenium`,
`dietary_chromium`, `dietary_molybdenum`, `dietary_chloride`,
`dietary_biotin`, `dietary_vitamin_a`, `dietary_vitamin_b6`,
`dietary_vitamin_b12`, `dietary_vitamin_c`, `dietary_vitamin_d`,
`dietary_vitamin_e`, `dietary_vitamin_k`, `dietary_folate`,
`dietary_niacin`, `dietary_pantothenic_acid`, `dietary_riboflavin`,
`dietary_thiamin`, `dietary_iodine`, `dietary_water`, `dietary_caffeine`

**Structured Types:**
`workouts`, `activity_summaries`, `ecg`

**Category Events:**
`high_heart_rate_event`, `low_heart_rate_event`,
`irregular_heart_rhythm_event`, `low_cardio_fitness_event`,
`mindful_session`, `handwashing_event`, `toothbrushing_event`,
`environmental_audio_exposure_event`, `headphone_audio_exposure_event`,
`apple_walking_steadiness_event`

**Reproductive Health:**
`menstrual_flow`, `intermenstrual_bleeding`, `ovulation_test_result`,
`cervical_mucus_quality`, `sexual_activity`, `contraceptive`,
`pregnancy`, `pregnancy_test_result`, `lactation`,
`progesterone_test_result`, `infrequent_menstrual_cycles`,
`irregular_menstrual_cycles`, `persistent_intermenstrual_bleeding`,
`prolonged_menstrual_periods`

**Symptoms:**
`abdominal_cramps`, `acne`, `appetite_changes`,
`generalized_body_ache`, `bloating`, `breast_pain`,
`chest_tightness_or_pain`, `chills`, `constipation`, `coughing`,
`diarrhea`, `dizziness`, `fainting`, `fatigue`, `fever`, `headache`,
`heartburn`, `hot_flashes`, `lower_back_pain`, `loss_of_smell`,
`loss_of_taste`, `mood_changes`, `nausea`, `pelvic_pain`,
`rapid_pounding_or_fluttering_heartbeat`, `runny_nose`,
`shortness_of_breath`, `sinus_congestion`, `skipped_heartbeat`,
`sleep_changes`, `sore_throat`, `vomiting`, `wheezing`,
`bladder_incontinence`, `dry_skin`, `hair_loss`, `vaginal_dryness`,
`memory_lapse`, `night_sweats`

**iOS 18+ Category Events:**
`bleeding_after_pregnancy`, `bleeding_during_pregnancy`, `sleep_apnea_event`

### Category Event Sample Format

Category events use the same batch structure as quantity metrics. The iOS app
sends `date`, `qty`, `source`, and, when available, `endDate` plus `rawValue`.
For duration-based events, `qty` is the duration in seconds and `rawValue`
keeps the raw HealthKit category value. For instant events without a duration,
`qty` is the raw HealthKit category value.

```json
{
  "metric": "mindful_session",
  "batch_index": 0,
  "total_batches": 1,
  "samples": [
    {
      "date": "2024-03-15T08:00:00Z",
      "endDate": "2024-03-15T08:15:00Z",
      "qty": 900,
      "rawValue": 0,
      "source": "Apple Watch"
    }
  ]
}
```

**Symptom category values:** `0` = not present, `1` = mild, `2` = moderate,
`3` = severe, `4` = unspecified.

**Menstrual flow values:** `1` = unspecified, `2` = light, `3` = medium,
`4` = heavy, `5` = none.

**Heart event values:** `0` = the event occurred (no severity scale).

All other metric names are accepted and stored in `quantity_samples` with:

```json
{
  "time": "sample date",
  "metric_name": "metric",
  "value": "qty",
  "unit": "unit",
  "source_id": "source"
}
```

## Sync Status

### `GET /api/apple/status`

Returns a flat JSON object. This shape is important: the HealthSave iOS app
reads each top-level value as a metric status object.

Correct response shape:

```json
{
  "heart_rate": {
    "count": 123,
    "oldest": "2026-04-01 08:00:00+00:00",
    "newest": "2026-04-10 12:00:00+00:00"
  },
  "hrv": {
    "count": 45,
    "oldest": "2026-04-01 08:00:00+00:00",
    "newest": "2026-04-10 12:00:00+00:00"
  },
  "blood_oxygen": {
    "count": 12,
    "oldest": "2026-04-02 09:00:00+00:00",
    "newest": "2026-04-09 21:00:00+00:00"
  },
  "daily_activity": {
    "count": 10,
    "oldest": "2026-04-01",
    "newest": "2026-04-10"
  },
  "sleep_sessions": {
    "count": 8,
    "oldest": "2026-04-02 23:10:00+00:00",
    "newest": "2026-04-10 06:45:00+00:00"
  },
  "workouts": {
    "count": 3,
    "oldest": "2026-04-03 17:30:00+00:00",
    "newest": "2026-04-08 18:15:00+00:00"
  },
  "quantity_samples": {
    "count": 900,
    "oldest": "2026-04-01 00:00:00+00:00",
    "newest": "2026-04-10 12:00:00+00:00"
  }
}
```

Do not wrap this endpoint as `{"status":"ok","counts":{...}}`; that shape is
not compatible with the current iOS status UI.

## Sync Receipts and Setup Diagnostics

These v2 operator endpoints are additive. They do not change the released v1
HealthSave ingest/status contract, but they make setup and end-to-end proof much
clearer.

## Compatibility tiers

HealthSave-compatible servers do **not** need to be Data Hub. The stable minimum
contract is split into a small core app/setup surface, recommended retry-safe
behavior, and optional Data Hub proof endpoints.

**Core app/setup contract**

1. `GET /api/health` returns a successful `2xx` liveness response. iOS 1.5+
   also accepts `GET /health` as a fallback — see "iOS liveness probe
   behavior" below.
2. `GET /api/apple/status` returns flat metric status objects.
3. `POST /api/apple/batch` accepts HealthSave metric batches and returns a
   successful `2xx` response for uploads it accepts.

**Recommended retry-safe behavior**

Servers should make `POST /api/apple/batch` idempotent by batch ID, run ID, or a
deterministic record key so retries and backfills do not double-count records.
This is strongly recommended for production destinations, but it is separate
from the minimal setup probe contract.

**Optional Data Hub extensions**

Data Hub also implements `GET /api/v2/sync/runs/latest` and
`GET /api/v2/sync/coverage` for richer receipt and coverage diagnostics.
HealthSave uses those only when present, so third-party servers can start with
the core contract and add receipt proof later. The iOS app reads run-specific
receipts via `GET /api/v2/sync/runs/{sync_run_id}` to light up its
"delivery receipt" confidence tier; a v1-only server still syncs cleanly and
simply doesn't unlock that tier.

### iOS liveness probe behavior (1.5+)

HealthSave 1.5 broadened the liveness probe so third-party servers don't fail
on plausible variations the v1 contract never pinned. Third-party
implementers should know the tolerances:

- **Endpoint discovery.** iOS calls `GET /api/health` first. If the response
  is `404`, iOS retries once at `GET /health`. Implement either one (or both);
  Data Hub exposes both.
- **Status-value accept-list.** The response `status` field is matched
  case-insensitively with surrounding whitespace trimmed against
  `{ "ok", "healthy", "alive", "ready", "up" }`. The reference Data Hub
  returns `"ok"`; other values in the set are accepted. Anything else
  (`"broken"`, `"error"`, `"down"`, `"starting"`, …) is rejected as
  not-HealthSave.
- **Authentication.** The configured `x-api-key` header is forwarded on the
  liveness request when the user has set one. Servers that protect
  `/api/health` (defense in depth) are welcome.
- **Auth classification.** `401` or `403` on the liveness path is classified
  as `authFailed` (the user sees "check your API key" copy), not
  `notHealthsave`. This means a key-rotation issue surfaces with actionable
  copy instead of pointing the user at the wrong problem.
- **Timeout.** 10 seconds on the liveness request.

These behaviors are pinned by `BackendCompatibilityTests` in the iOS repo;
see `ios_app/Sources/HealthSync/BackendCompatibility.swift` for the source of
truth.

### `GET /api/v2/setup/diagnostics`

Unauthenticated, no health data. Use this to confirm that a base URL points at
Data Hub API rather than Grafana or Homepage.

Example response:

```json
{
  "service": "health-data-hub",
  "kind": "HealthSave Data Hub API",
  "status": "ok",
  "auth_required": true,
  "health_endpoint": "/api/health",
  "status_endpoint": "/api/apple/status",
  "ingest_endpoint": "/api/apple/batch",
  "latest_sync_endpoint": "/api/v2/sync/runs/latest",
  "coverage_endpoint": "/api/v2/sync/coverage",
  "grafana_required": false,
  "wrong_port_hint": "If you see Grafana auth JSON or Homepage HTML 404, the app is pointed at the wrong port. Use the Data Hub API base URL, not Grafana/Homepage."
}
```

### HealthSave sync receipt headers

The released iOS app already sends these optional headers on batch sync:

- `Idempotency-Key`
- `X-HealthSave-Sync-Run-ID`
- `X-HealthSave-Batch-ID`
- `X-HealthSave-Payload-Hash`
- `X-HealthSave-Metric`
- `X-HealthSave-Batch-Index`
- `X-HealthSave-Total-Batches`
- `X-HealthSave-Sync-Mode`
- `X-HealthSave-Anchor-Present`
- `X-HealthSave-Lower-Bound-Reason`
- `X-HealthSave-Full-Export`
- `X-HealthSave-Query-Lower-Bound`
- `X-HealthSave-Sample-Min-Time`
- `X-HealthSave-Sample-Max-Time`

Data Hub records them in `healthsave_sync_receipts` so operators can prove that a
sync reached the API, see which batches were processed, and separate delivery
receipt time from sample-window freshness and Grafana dashboard visibility.
If the same `Idempotency-Key` is reused with a different payload hash, Data Hub
returns `409 Conflict` and does not ingest the replacement payload.

### `GET /api/v2/sync/runs/latest`

Protected by `x-api-key` when `API_KEY` is set. Returns the latest observed
HealthSave sync run with batch counts, accepted / rejected / in-batch-deduped
record counts, and metric names.

### `GET /api/v2/sync/runs/{sync_run_id}`

Protected by `x-api-key` when `API_KEY` is set. Returns the delivery receipt
summary for one HealthSave sync run. This endpoint proves Data Hub saw the
batches HealthSave sent; it is not a full sample-by-sample manifest verifier.

Example response:

```json
{
  "status": "ok",
  "sync_run_id": "run_01HY...",
  "receipt_id": "run_01HY...",
  "verification_level": "delivery_receipt",
  "records_received": 512,
  "records_accepted": 488,
  "records_inserted_new": null,
  "records_deduped_existing": null,
  "storage_result_level": "accepted_only",
  "records_skipped": 0,
  "records_rejected": 0,
  "records_deduped_in_batch": 24,
  "sample_window": {
    "min_sample_time": "2026-05-24T07:10:00Z",
    "max_sample_time": "2026-05-24T07:13:00Z"
  },
  "latest_sample_time": "2026-05-24T07:13:00Z",
  "batches_seen": 2,
  "batches_processed": 2,
  "batches_failed": 0,
  "metrics": ["heart_rate", "step_count"],
  "oldest_received_at": "2026-05-24T07:12:00Z",
  "newest_receipt_at": "2026-05-24T07:13:22Z"
}
```

**Honest accounting (1.5+).** `records_rejected` (and the persisted
`records_skipped`) count ONLY true validation failures — samples missing a
parseable time/value/date. They never include aggregation rollup (sleep stage
samples folded into sessions are preserved in `sleep_stages`) nor
`records_deduped_in_batch` (legitimate HealthKit full-export overlap collapsed
on the conflict key). A healthy full-history sync therefore reports
`records_rejected: 0`, not a large number derived from
`records_received - records_accepted`. In the example above, 512 received
samples yielded 488 unique rows with 24 in-batch duplicates collapsed and 0
genuine rejections.

### `GET /api/v2/sync/coverage`

Protected by `x-api-key` when `API_KEY` is set. Returns metric-level receipt
coverage and destination sample coverage. `newest_receipt_at` proves delivery
time; `latest_destination_sample_time` proves the newest sample currently stored
for that metric. They are intentionally separate because a recent receipt can
contain old samples.

The Timescale writer splits accepted rows into inserted-new vs deduped-existing
(`storage_result_level: inserted_vs_existing`) and reports true
`records_rejected` plus `records_deduped_in_batch` counts. Backends that cannot
distinguish inserted-vs-existing leave those fields nullable and report
`storage_result_level: accepted_only`.

## Insights

These endpoints are server-side analysis surfaces. They do not change the
HealthSave iOS ingestion/status contract.

### `GET /api/insights/anomalies`

Returns recent anomaly findings. Optional query parameters:

- `since`: ISO-8601 lower bound on finding creation time
- `severity`: comma-separated list of `info`, `watch`, `alert`

### `GET /api/insights/trends`

Returns persisted HR / HRV trend findings from the statistical engine.
Optional query parameters:

- `period`: day window such as `30d` or `90d`

Example response:

```json
{
  "trends": [
    {
      "metric": "hrv",
      "slope": -0.9,
      "direction": "down",
      "period_days": 30,
      "p_value": 0.02,
      "confidence": "medium"
    }
  ],
  "count": 1
}
```

## v2 read API (evolving)

> **Status: evolving — not a frozen contract.** Unlike the v1 ingest surface
> above (byte-locked for the HealthSave iOS app), the `/api/v2/*` read plane is
> under active development; request/response shapes may change between releases.
> Treat it as pre-stable. **Auth:** routes marked `key` require the `X-API-Key`
> header when `API_KEY` is set; routes marked `open` are intentionally
> unauthenticated; the Whoop webhook authenticates via its HMAC signature, not
> `X-API-Key`.

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v2/meta` | GET | open | v2 version axes (api_contract / ontology / normalizer / fusion_policy) |
| `/api/v2/setup/diagnostics` | GET | open | self-describe the service so a misconfigured client (e.g. pointed at Grafana) detects it |
| `/api/v2/metrics` | GET | open | list available canonical metrics |
| `/api/v2/metrics/{metric_id}/series` | GET | key | time-series for one metric |
| `/api/v2/sources` | GET | key | Source integrations (Source/Device/Stream identity) |
| `/api/v2/devices` | GET | key | distinct device emitters (derived from streams) |
| `/api/v2/streams` | GET | key | source-device streams with stable UUIDs (HA keys on these) |
| `/api/v2/streams/{stream_id}` | GET | key | one source-device stream |
| `/api/v2/insights/latest` | GET | key | latest daily-briefing + weekly-summary narratives |
| `/api/v2/insights/correlations` | GET | key | recent cross-metric correlation findings |
| `/api/v2/insights/findings` | GET | key | recent structured analysis findings |
| `/api/v2/insights/trigger` | POST | key | run a briefing / trend / analysis job on demand |
| `/api/v2/sync/runs/latest` | GET | key | latest sync-run summary |
| `/api/v2/sync/runs/{sync_run_id}` | GET | key | per-run delivery-receipt summary |
| `/api/v2/sync/coverage` | GET | key | per-metric receipt-vs-destination freshness |
| `/api/v2/sync/anomalies` | GET | key | overlapping-sync-run + coverage anomalies |
| `/api/v2/experiments` | GET, POST | key | list / create self-experiments |
| `/api/v2/experiments/candidates` | GET | key | suggested experiments |
| `/api/v2/experiments/{experiment_id}` | GET | key | one experiment |
| `/api/v2/experiments/{experiment_id}/analyze` | POST | key | analyze an experiment's result |
| `/api/v2/experiments/{experiment_id}/abandon` | POST | key | abandon an experiment |
| `/api/v2/agents/proposals` | GET | key | pending agent action proposals |
| `/api/v2/agents/proposals/{proposal_id}/decide` | POST | key | approve / reject a proposal |
| `/api/v2/readiness` | GET | key | readiness / recovery summary |
| `/api/v2/privacy` | GET | key | egress policy + audit (what derived data may leave the host) |
| `/api/v2/export/metrics` | GET | key | list exportable metrics with counts + date ranges |
| `/api/v2/export` | GET | key | export one metric (or `all`) as JSON or CSV |
| `/api/v2/sources/whoop/webhook` | POST | HMAC | Whoop push webhook; authenticity via `X-WHOOP-Signature` |

## Compatibility Notes

- Timestamp values should be ISO 8601 strings. A trailing `Z` is accepted.
- Date-only daily activity values can use `YYYY-MM-DD` or an ISO timestamp.
- Batch ingestion is idempotent for first-class time-series tables through
  `ON CONFLICT` upserts, including sleep sessions and workouts.
- Unknown metric names are intentionally accepted. Unknown quantity-like
  samples with `date` and `qty` can be stored before they receive first-class
  dashboards.
- Invalid quantity samples are skipped instead of failing the whole batch.
