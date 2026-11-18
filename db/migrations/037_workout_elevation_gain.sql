-- 037_workout_elevation_gain.sql
--
-- Each workout's total elevation gain, in metres.
--
-- The phone app sends it as `elevationGain` on a workouts sample when the
-- watch recorded one (iPhone app 1.9.4 and later). Until now the server had
-- nowhere to keep it. Workouts stored before this migration, and workouts a
-- device recorded without one, read back as NULL; a workout the phone sends
-- again fills it in.
--
-- Additive only: one new nullable column; no row changes.
BEGIN;

ALTER TABLE workouts
    ADD COLUMN IF NOT EXISTS elevation_gain_m FLOAT;

COMMIT;
