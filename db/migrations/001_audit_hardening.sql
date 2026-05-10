-- Applies the schema hardening added after the initial public release.
-- Run this against existing databases before restarting the updated API.

CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_device_type ON devices (device_type);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sleep_sessions_device_start
    ON sleep_sessions (device_id, start_time);

DROP INDEX IF EXISTS uq_sleep_stages;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sleep_stages
    ON sleep_stages (time, device_id, stage);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workouts_device_start
    ON workouts (device_id, start_time);

CREATE INDEX IF NOT EXISTS idx_raw_ingestion_log_ingested_at
    ON raw_ingestion_log (ingested_at DESC);
