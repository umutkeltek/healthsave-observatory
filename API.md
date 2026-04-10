# HealthSave API Contract

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

## Compatibility Notes

- Timestamp values should be ISO 8601 strings. A trailing `Z` is accepted.
- Date-only daily activity values can use `YYYY-MM-DD` or an ISO timestamp.
- Batch ingestion is idempotent for first-class time-series tables through
  `ON CONFLICT` upserts.
- Unknown metric names are intentionally accepted. Unknown quantity-like
  samples with `date` and `qty` can be stored before they receive first-class
  dashboards.
