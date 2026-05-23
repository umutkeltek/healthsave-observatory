-- 010_source_id_on_dedicated_whoop_tables.sql
--
-- Preserve source identity on dedicated tables used by poll-based sources.
-- Whoop normalization already emits source='Whoop' for SpO2, skin
-- temperature, and workouts, but these tables previously had nowhere
-- to store it. The public dashboards can then distinguish Apple Watch,
-- Whoop, and future providers without copying the private personal
-- stack's legacy recovery-table shape.

BEGIN;

ALTER TABLE blood_oxygen
    ADD COLUMN IF NOT EXISTS source_id TEXT;

ALTER TABLE body_temperature
    ADD COLUMN IF NOT EXISTS source_id TEXT;

ALTER TABLE workouts
    ADD COLUMN IF NOT EXISTS source_id TEXT;

CREATE INDEX IF NOT EXISTS idx_blood_oxygen_source_time
    ON blood_oxygen (source_id, time DESC)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_body_temperature_source_time
    ON body_temperature (source_id, time DESC)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_workouts_source_start
    ON workouts (source_id, start_time DESC)
    WHERE source_id IS NOT NULL;

COMMIT;
