-- 024_apple_daily_total_revisions.sql
--
-- Repair Apple HealthKit Statistics rows written before normalizer v0.2.0.
-- Those rows are owner-level daily totals, but their value-dependent dedup key
-- left every corrected total active. Preserve every historical row: rank by
-- immutable canonical-row creation time, mark older variants superseded, and
-- give the latest variant the same stable identity new ingest now derives.
--
-- This is an intentionally irreversible data correction. Raw observations and
-- raw_ingestion_log lineage remain available; reversal would re-expose known
-- duplicate active totals. Rows are classified either by their registered
-- HealthKit Statistics stream or, for legacy NULL/unregistered streams, by a
-- conservative raw batch whose every sample has that same normalized origin.
-- Ambiguous/missing raw lineage is left untouched. The temporary plan makes all
-- updates share one snapshot and disappears at commit.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Exact successful retries must be true no-ops. New receipts record their
-- owner and the complete frozen T0 response; legacy rows stay NULL and are
-- deliberately non-replayable because their owner cannot be proven.
ALTER TABLE healthsave_sync_receipts
    ADD COLUMN IF NOT EXISTS owner_id UUID,
    ADD COLUMN IF NOT EXISTS response_payload JSONB;

-- ``processing`` is an uncommitted ingest claim. The claim and its frozen
-- successful response are committed atomically with canonical/projection data,
-- so healthy readers never observe this state after a request completes.
ALTER TABLE healthsave_sync_receipts
    DROP CONSTRAINT IF EXISTS healthsave_sync_receipts_status_check;
ALTER TABLE healthsave_sync_receipts
    ADD CONSTRAINT healthsave_sync_receipts_status_check
    CHECK (status IN ('processed', 'empty', 'failed', 'processing'));

-- The original indexes made keys global. That lets one owner's collision
-- either overwrite another owner's receipt or prevent the second receipt from
-- being recorded. Legacy NULL-owner rows are intentionally outside the new
-- indexes; they cannot be authenticated and remain non-replayable.
DROP INDEX IF EXISTS uq_healthsave_sync_receipts_batch_id;
DROP INDEX IF EXISTS uq_healthsave_sync_receipts_idempotency_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_healthsave_sync_receipts_owner_batch_id
    ON healthsave_sync_receipts (owner_id, batch_id)
    WHERE owner_id IS NOT NULL AND batch_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_healthsave_sync_receipts_owner_idempotency_key
    ON healthsave_sync_receipts (owner_id, idempotency_key)
    WHERE owner_id IS NOT NULL AND idempotency_key IS NOT NULL;

CREATE TEMP TABLE apple_daily_total_revision_repair ON COMMIT DROP AS
WITH eligible AS (
    SELECT
        observation.id AS observation_id,
        observation.owner_id,
        observation.workspace_id,
        observation.source_id,
        observation.metric_id,
        observation.interval_start,
        observation.device_id,
        observation.stream_id,
        observation.provenance,
        observation.created_at,
        CASE
            WHEN pg_input_is_valid(
                coalesce(observation.provenance->>'raw_payload_ref', ''),
                'bigint'
            )
            THEN (observation.provenance->>'raw_payload_ref')::bigint
        END AS raw_log_id
    FROM canonical_observations AS observation
    WHERE observation.normalizer_id = 'apple_health'
      AND observation.status = 'active'
      AND observation.value_type = 'quantity'
      AND observation.metric_id IN (
          'metabolic.insulin_delivery',
          'activity.steps',
          'activity.active_energy',
          'activity.basal_energy',
          'activity.exercise_minutes',
          'activity.stand_minutes',
          'activity.move_minutes',
          'activity.flights_climbed',
          'activity.distance_walking_running',
          'activity.distance_cycling',
          'activity.distance_swimming',
          'activity.distance_wheelchair',
          'activity.distance_downhill_snow_sports',
          'activity.distance_cross_country_skiing',
          'activity.distance_paddle_sports',
          'activity.distance_rowing',
          'activity.distance_skating_sports',
          'activity.push_count',
          'activity.swimming_stroke_count',
          'activity.nike_fuel',
          'mobility.times_fallen',
          'respiratory.inhaler_usage',
          'environment.time_in_daylight',
          'nutrition.energy_consumed',
          'nutrition.carbohydrates',
          'nutrition.protein',
          'nutrition.fat_total',
          'nutrition.fat_saturated',
          'nutrition.fat_monounsaturated',
          'nutrition.fat_polyunsaturated',
          'nutrition.cholesterol',
          'nutrition.fiber',
          'nutrition.sugar',
          'nutrition.water',
          'nutrition.caffeine',
          'nutrition.calcium',
          'nutrition.iron',
          'nutrition.magnesium',
          'nutrition.phosphorus',
          'nutrition.potassium',
          'nutrition.sodium',
          'nutrition.chloride',
          'nutrition.zinc',
          'nutrition.copper',
          'nutrition.manganese',
          'nutrition.selenium',
          'nutrition.iodine',
          'nutrition.chromium',
          'nutrition.molybdenum',
          'nutrition.vitamin_a',
          'nutrition.vitamin_c',
          'nutrition.vitamin_d',
          'nutrition.vitamin_e',
          'nutrition.vitamin_k',
          'nutrition.thiamin',
          'nutrition.riboflavin',
          'nutrition.niacin',
          'nutrition.pantothenic_acid',
          'nutrition.vitamin_b6',
          'nutrition.biotin',
          'nutrition.folate',
          'nutrition.vitamin_b12',
          'nutrition.alcoholic_beverages'
      )
),
identity_hashes AS (
    SELECT
        eligible.*,
        digest(
            uuid_send('9e1b7c34-5a2d-4f6e-8b0a-3c7d9f1e2a64'::uuid)
                || convert_to(
                    eligible.owner_id::text
                        || ':apple-healthkit-ios:healthkit statistics',
                    'UTF8'
                ),
            'sha1'
        ) AS stream_hash,
        digest(
            uuid_send('9e1b7c34-5a2d-4f6e-8b0a-3c7d9f1e2a64'::uuid)
                || convert_to(
                    'source:' || eligible.owner_id::text || ':apple-healthkit-ios',
                    'UTF8'
                ),
            'sha1'
        ) AS source_hash
    FROM eligible
),
expected_identities AS (
    SELECT
        identity_hashes.*,
        encode(
            set_byte(
                set_byte(
                    substring(identity_hashes.stream_hash FROM 1 FOR 16),
                    6,
                    (get_byte(identity_hashes.stream_hash, 6) & 15) | 80
                ),
                8,
                (get_byte(identity_hashes.stream_hash, 8) & 63) | 128
            ),
            'hex'
        )::uuid AS expected_stream_id,
        encode(
            set_byte(
                set_byte(
                    substring(identity_hashes.source_hash FROM 1 FOR 16),
                    6,
                    (get_byte(identity_hashes.source_hash, 6) & 15) | 80
                ),
                8,
                (get_byte(identity_hashes.source_hash, 8) & 63) | 128
            ),
            'hex'
        )::uuid AS expected_source_id
    FROM identity_hashes
),
registry_proven AS (
    SELECT
        identity.observation_id,
        identity.owner_id,
        identity.workspace_id,
        identity.interval_start
    FROM expected_identities AS identity
    JOIN source_device_streams AS stream
      ON stream.id = identity.stream_id
     AND stream.id = identity.expected_stream_id
     AND stream.owner_id = identity.owner_id
     AND stream.source_plugin_id = 'apple-healthkit-ios'
     AND stream.origin_key = 'healthkit statistics'
),
raw_proven AS (
    SELECT
        identity.observation_id,
        identity.owner_id,
        identity.workspace_id,
        identity.interval_start
    FROM expected_identities AS identity
    JOIN raw_ingestion_log AS raw
      ON raw.id = identity.raw_log_id
     AND raw.source_type = 'healthsave'
     AND raw.endpoint = '/api/apple/batch'
    WHERE (identity.stream_id IS NULL OR identity.stream_id = identity.expected_stream_id)
      AND jsonb_typeof(raw.raw_payload->'samples') = 'array'
      AND jsonb_array_length(raw.raw_payload->'samples') > 0
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(raw.raw_payload->'samples') AS sample(value)
          CROSS JOIN LATERAL (
              SELECT coalesce(
                  sample.value->>'source',
                  sample.value->>'source_id',
                  sample.value->>'sourceName',
                  sample.value->>'device',
                  sample.value->>'deviceName',
                  sample.value->>'device_id',
                  'HealthSave'
              ) AS raw_origin
          ) AS origin
          WHERE jsonb_typeof(sample.value) <> 'object'
             OR CASE
                    WHEN btrim(origin.raw_origin) = '' THEN 'healthsave'
                    ELSE lower(
                        regexp_replace(
                            btrim(origin.raw_origin),
                            '[[:space:]]+',
                            ' ',
                            'g'
                        )
                    )
                END <> 'healthkit statistics'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM source_device_streams AS conflicting_stream
          WHERE conflicting_stream.owner_id = identity.owner_id
            AND conflicting_stream.source_plugin_id = 'apple-healthkit-ios'
            AND conflicting_stream.origin_key = 'healthkit statistics'
            AND conflicting_stream.id <> identity.expected_stream_id
      )
),
proven AS (
    SELECT * FROM registry_proven
    UNION
    SELECT * FROM raw_proven
),
candidates AS (
    SELECT
        identity.observation_id,
        identity.owner_id,
        identity.workspace_id,
        identity.source_id,
        identity.metric_id,
        identity.interval_start,
        identity.created_at,
        identity.expected_source_id,
        identity.expected_stream_id,
        'xik:v1:' || encode(
            digest(
                concat_ws(
                    chr(31),
                    identity.owner_id::text,
                    identity.source_id::text,
                    'apple_healthkit_daily_total',
                    'composite',
                    identity.workspace_id::text,
                    identity.metric_id,
                    trunc(extract(epoch FROM identity.interval_start) * 1000000)::bigint::text,
                    coalesce(identity.device_id::text, ''),
                    identity.expected_stream_id::text
                ),
                'sha256'
            ),
            'hex'
        ) AS stable_exact_ingest_key,
        row_number() OVER (
            PARTITION BY
                identity.owner_id,
                identity.workspace_id,
                identity.source_id,
                identity.metric_id,
                identity.interval_start,
                identity.device_id,
                identity.expected_stream_id
            ORDER BY
                -- ON CONFLICT retries update provenance in place but never
                -- created_at. Rank immutable row creation first so
                -- A -> B -> exact retry A keeps B. A true later revert to
                -- byte-identical A is intrinsically indistinguishable here.
                identity.created_at DESC,
                CASE
                    WHEN identity.raw_log_id IS NOT NULL THEN identity.raw_log_id
                END DESC NULLS LAST,
                CASE
                    WHEN pg_input_is_valid(
                        coalesce(identity.provenance->>'captured_at', ''),
                        'timestamp with time zone'
                    )
                    THEN (identity.provenance->>'captured_at')::timestamptz
                END DESC NULLS LAST,
                identity.observation_id DESC
        ) AS revision_rank
    FROM expected_identities AS identity
    JOIN proven
      ON proven.observation_id = identity.observation_id
     AND proven.owner_id = identity.owner_id
     AND proven.workspace_id = identity.workspace_id
     AND proven.interval_start = identity.interval_start
)
SELECT
    candidates.*,
    encode(
        digest(
            concat_ws(
                '|',
                candidates.owner_id::text,
                candidates.workspace_id::text,
                candidates.source_id::text,
                candidates.stable_exact_ingest_key
            ),
            'sha256'
        ),
        'hex'
    ) AS stable_dedup_key
FROM candidates;

-- Restore the registry rows that legacy/fail-soft canonical writes may lack.
INSERT INTO sources (
    id, owner_id, plugin_id, display_name, first_seen_at, last_seen_at
)
SELECT
    repair.expected_source_id,
    repair.owner_id,
    'apple-healthkit-ios',
    'apple-healthkit-ios',
    min(repair.created_at),
    max(repair.created_at)
FROM apple_daily_total_revision_repair AS repair
GROUP BY repair.expected_source_id, repair.owner_id
ON CONFLICT (owner_id, plugin_id) DO UPDATE SET
    first_seen_at = least(sources.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at = greatest(sources.last_seen_at, EXCLUDED.last_seen_at);

INSERT INTO source_device_streams (
    id, owner_id, source_plugin_id, origin_key, device_label,
    first_seen_at, last_seen_at
)
SELECT
    repair.expected_stream_id,
    repair.owner_id,
    'apple-healthkit-ios',
    'healthkit statistics',
    'HealthKit Statistics',
    min(repair.created_at),
    max(repair.created_at)
FROM apple_daily_total_revision_repair AS repair
GROUP BY repair.expected_stream_id, repair.owner_id
ON CONFLICT (owner_id, source_plugin_id, origin_key) DO UPDATE SET
    device_label = EXCLUDED.device_label,
    first_seen_at = least(source_device_streams.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at = greatest(source_device_streams.last_seen_at, EXCLUDED.last_seen_at);

-- Move historical variants off the stable unique key first, so the winner can
-- claim it even if a v0.2.0 row arrived just before this migration ran.
UPDATE canonical_observations AS observation
SET
    status = 'superseded',
    aggregation_scope = 'owner_all_source_day_total',
    stream_id = repair.expected_stream_id,
    exact_ingest_key = repair.stable_exact_ingest_key,
    dedup_key = encode(
        digest(
            concat_ws(
                chr(31),
                'superseded:v1',
                observation.owner_id::text,
                observation.workspace_id::text,
                observation.id::text,
                trunc(extract(epoch FROM observation.interval_start) * 1000000)::bigint::text,
                observation.dedup_key
            ),
            'sha256'
        ),
        'hex'
    )
FROM apple_daily_total_revision_repair AS repair
WHERE repair.revision_rank > 1
  AND observation.id = repair.observation_id
  AND observation.owner_id = repair.owner_id
  AND observation.workspace_id = repair.workspace_id
  AND observation.interval_start = repair.interval_start;

UPDATE canonical_observations AS observation
SET
    aggregation_scope = 'owner_all_source_day_total',
    stream_id = repair.expected_stream_id,
    exact_ingest_key = repair.stable_exact_ingest_key,
    dedup_key = repair.stable_dedup_key
FROM apple_daily_total_revision_repair AS repair
WHERE repair.revision_rank = 1
  AND observation.id = repair.observation_id
  AND observation.owner_id = repair.owner_id
  AND observation.workspace_id = repair.workspace_id
  AND observation.interval_start = repair.interval_start;

COMMIT;
