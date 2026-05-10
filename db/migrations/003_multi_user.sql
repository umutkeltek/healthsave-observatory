-- 003_multi_user.sql
--
-- Multi-user / household support: add an owner_id UUID column to every
-- metric table so multiple residents can ingest into the same stack.
--
-- Backward-compatible by construction:
--   * owner_id is NOT NULL with a default of the single-user sentinel
--     '00000000-0000-0000-0000-000000000001'. Existing rows are
--     populated with that sentinel automatically.
--   * Ingest paths default to the same sentinel when the X-User-Id
--     header is absent, so existing single-user installs keep working
--     without any client change.
--   * Unique indexes and primary keys are widened to include owner_id
--     so two residents can have a sample at the same (time, device_id)
--     without colliding.

BEGIN;

-- Heart rate
ALTER TABLE heart_rate
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_heart_rate;
CREATE UNIQUE INDEX uq_heart_rate ON heart_rate (time, device_id, owner_id);

-- HRV
ALTER TABLE hrv
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_hrv;
CREATE UNIQUE INDEX uq_hrv ON hrv (time, device_id, owner_id);

-- Blood oxygen
ALTER TABLE blood_oxygen
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_blood_oxygen;
CREATE UNIQUE INDEX uq_blood_oxygen ON blood_oxygen (time, device_id, owner_id);

-- Body temperature
ALTER TABLE body_temperature
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_body_temperature;
CREATE UNIQUE INDEX uq_body_temperature ON body_temperature (time, device_id, owner_id);

-- Daily activity (had a primary key, not a unique index)
ALTER TABLE daily_activity
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE daily_activity DROP CONSTRAINT IF EXISTS daily_activity_pkey;
ALTER TABLE daily_activity ADD PRIMARY KEY (date, device_id, owner_id);

-- Sleep sessions
ALTER TABLE sleep_sessions
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_sleep_sessions_device_start;
CREATE UNIQUE INDEX uq_sleep_sessions_device_start
    ON sleep_sessions (device_id, start_time, owner_id);

-- Sleep stages
ALTER TABLE sleep_stages
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_sleep_stages;
CREATE UNIQUE INDEX uq_sleep_stages ON sleep_stages (time, device_id, stage, owner_id);

-- Workouts
ALTER TABLE workouts
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_workouts_device_start;
CREATE UNIQUE INDEX uq_workouts_device_start
    ON workouts (device_id, start_time, owner_id);

-- Recovery
ALTER TABLE recovery
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_recovery;
CREATE UNIQUE INDEX uq_recovery ON recovery (time, device_id, owner_id);

-- Stress
ALTER TABLE stress
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
DROP INDEX IF EXISTS uq_stress;
CREATE UNIQUE INDEX uq_stress ON stress (time, device_id, owner_id);

-- Quantity samples (catch-all). The original schema declared a PRIMARY KEY
-- on (time, device_id, metric_name); widen it to include owner_id.
ALTER TABLE quantity_samples
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE quantity_samples DROP CONSTRAINT IF EXISTS quantity_samples_pkey;
ALTER TABLE quantity_samples
    ADD PRIMARY KEY (time, device_id, metric_name, owner_id);

COMMIT;
