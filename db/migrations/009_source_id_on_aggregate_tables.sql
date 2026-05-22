-- 009_source_id_on_aggregate_tables.sql
--
-- Add source_id TEXT to the two aggregate tables that key on
-- device_id alone today — daily_activity and sleep_sessions. Without
-- this, the HA-MQTT bridge cannot split "steps today" or "last sleep
-- hours" per Apple Watch vs Whoop vs iPhone, while heart_rate / hrv
-- already carry source_id natively in the schema.
--
-- Backward-compatible by construction:
--   * source_id NULL by default; existing rows stay NULL.
--   * Ingest paths populate the column when the incoming sample's
--     "source" field is present; otherwise the row lands with NULL
--     and the per-source reader collapses it under the "unknown"
--     bucket (see homeassistant_mqtt.snapshot.source_slug).
--   * Indexes on (source_id, date) and (source_id, start_time) make
--     the per-source latest-value reads cheap.
--   * No primary key / unique-index changes — existing PK
--     (date, device_id, owner_id) for daily_activity and existing
--     unique index (device_id, start_time, owner_id) for
--     sleep_sessions stay correct: a single source per (device,
--     timestamp) is the de-facto invariant. Two sources cannot both
--     own the same nightly sleep on the same watch.

BEGIN;

ALTER TABLE daily_activity
    ADD COLUMN IF NOT EXISTS source_id TEXT;

ALTER TABLE sleep_sessions
    ADD COLUMN IF NOT EXISTS source_id TEXT;

CREATE INDEX IF NOT EXISTS idx_daily_activity_source_date
    ON daily_activity (source_id, date DESC)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sleep_sessions_source_start
    ON sleep_sessions (source_id, start_time DESC)
    WHERE source_id IS NOT NULL;

COMMIT;
