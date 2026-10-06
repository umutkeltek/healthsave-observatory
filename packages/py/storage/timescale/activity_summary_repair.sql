-- Restore missing summary fields from processed raw payloads into existing
-- daily_activity rows. Run through psql with explicit owner_id, start_date,
-- end_date and through_raw_id variables. Preview is read-only by default;
-- apply=true requires separate operator authorization before live execution.
--
-- Keeps the legacy writer's date mapping (the YYYY-MM-DD portion of date).
-- Does not reinterpret localDate, create daily rows, or change existing values.
-- Chooses the newest processed value per field and day through the reviewed
-- raw-log snapshot; never replays failed/unprocessed receipts or canonical data.
\set ON_ERROR_STOP on
\if :{?apply}
\else
    \set apply false
\endif

\if :apply
BEGIN;
\else
BEGIN READ ONLY;
\endif

WITH raw_summary_samples AS (
    SELECT
        raw.id AS raw_log_id,
        raw.device_id,
        receipt.owner_id,
        raw.ingested_at,
        sample.value AS sample,
        sample.ordinality,
        daily.date AS sample_date
    FROM raw_ingestion_log raw
    JOIN healthsave_sync_receipts receipt
        ON receipt.raw_log_id = raw.id
       AND receipt.owner_id = :'owner_id'::uuid
       AND receipt.status = 'processed'
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(raw.raw_payload->'samples') = 'array'
             THEN raw.raw_payload->'samples' ELSE '[]'::jsonb END
    ) WITH ORDINALITY sample(value, ordinality)
    JOIN daily_activity daily
        ON daily.owner_id = receipt.owner_id
       AND daily.device_id = raw.device_id
       AND daily.date::text = left(sample.value->>'date', 10)
    WHERE raw.source_type = 'healthsave'
      AND raw.processed IS TRUE
      AND raw.raw_payload->>'metric' = 'activity_summaries'
      AND raw.id <= :'through_raw_id'::bigint
      AND daily.date BETWEEN :'start_date'::date AND :'end_date'::date
), numeric_fields AS (
    SELECT samples.*, field.destination, field.priority,
           (samples.sample->>field.source_key)::double precision AS field_value
    FROM raw_summary_samples samples
    CROSS JOIN (VALUES
        ('active_energy', 'active_calories', 0),
        ('activeEnergyBurned', 'active_calories', 1),
        ('exercise_minutes', 'active_minutes', 0),
        ('appleExerciseTime', 'active_minutes', 1),
        ('stand_hours', 'stand_hours', 0),
        ('appleStandHours', 'stand_hours', 1)
    ) field(source_key, destination, priority)
    WHERE jsonb_typeof(samples.sample->field.source_key) = 'number'
), latest_fields AS (
    SELECT DISTINCT ON (owner_id, device_id, sample_date, destination)
           owner_id, device_id, sample_date, destination, field_value, raw_log_id
    FROM numeric_fields
    ORDER BY owner_id, device_id, sample_date, destination,
             ingested_at DESC, raw_log_id DESC, ordinality DESC, priority DESC
), candidates AS (
    SELECT owner_id, device_id, sample_date, max(raw_log_id) AS newest_source_raw_id,
           max(field_value) FILTER (WHERE destination = 'active_calories') AS active_calories,
           max(field_value) FILTER (WHERE destination = 'active_minutes') AS active_minutes,
           max(field_value) FILTER (WHERE destination = 'stand_hours') AS stand_hours
    FROM latest_fields
    GROUP BY owner_id, device_id, sample_date
)
\if :apply
, repaired AS (
    UPDATE daily_activity daily
    SET active_calories = coalesce(daily.active_calories, candidate.active_calories),
        active_minutes = coalesce(daily.active_minutes, trunc(candidate.active_minutes)::int),
        stand_hours = coalesce(daily.stand_hours, trunc(candidate.stand_hours)::int)
    FROM candidates candidate
    WHERE daily.owner_id = candidate.owner_id
      AND daily.device_id = candidate.device_id
      AND daily.date = candidate.sample_date
      AND (
          (daily.active_calories IS NULL AND candidate.active_calories IS NOT NULL)
          OR (daily.active_minutes IS NULL AND candidate.active_minutes IS NOT NULL)
          OR (daily.stand_hours IS NULL AND candidate.stand_hours IS NOT NULL)
      )
    RETURNING 1
)
SELECT json_build_object('mode', 'apply', 'rows_updated', count(*)) FROM repaired;
COMMIT;
\else
SELECT json_build_object(
    'mode', 'dry_run',
    'through_raw_id', :'through_raw_id'::bigint,
    'rows_to_repair', count(*),
    'active_calories_to_fill', count(*) FILTER (
        WHERE daily.active_calories IS NULL AND candidate.active_calories IS NOT NULL),
    'active_minutes_to_fill', count(*) FILTER (
        WHERE daily.active_minutes IS NULL AND candidate.active_minutes IS NOT NULL),
    'stand_hours_to_fill', count(*) FILTER (
        WHERE daily.stand_hours IS NULL AND candidate.stand_hours IS NOT NULL),
    'oldest_date_to_repair', min(candidate.sample_date),
    'newest_date_to_repair', max(candidate.sample_date),
    'newest_source_raw_id', max(candidate.newest_source_raw_id)
)
FROM candidates candidate
JOIN daily_activity daily
    ON daily.owner_id = candidate.owner_id
   AND daily.device_id = candidate.device_id
   AND daily.date = candidate.sample_date
WHERE (daily.active_calories IS NULL AND candidate.active_calories IS NOT NULL)
   OR (daily.active_minutes IS NULL AND candidate.active_minutes IS NOT NULL)
   OR (daily.stand_hours IS NULL AND candidate.stand_hours IS NOT NULL);
ROLLBACK;
\endif
