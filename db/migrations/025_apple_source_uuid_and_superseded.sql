-- 025_apple_source_uuid_and_superseded.sql
--
-- Identity-aware columns on the v1 dedicated tables for Apple HealthKit ingest.
-- Pre-migration these tables keyed on (time, device_id, owner_id) — Apple
-- HealthKit revises resting-heart-rate and reshuffles sleep via
-- delete-and-reinsert, so the v1 path silently landed two values for the day.
-- This migration adds:
--   * `source_uuid UUID` on heart_rate, hrv, blood_oxygen, body_temperature,
--     sleep_sessions. Nullable + partial unique index so it doesn't fight the
--     existing (time, device_id, owner_id) uniqueness for legacy rows that
--     arrived before the iOS client learned to send UUIDs.
--   * The four dedicated tables are TimescaleDB hypertables partitioned on
--     `time` — Postgres/Timescale requires EVERY unique index on a hypertable
--     to include the partitioning column, so their identity indexes are
--     (owner_id, source_uuid, time). Same uuid always implies same time
--     (HKSample.startDate is immutable per uuid), so the extra column costs
--     no idempotency. The matching ON CONFLICT clause must repeat the index's
--     partial predicate (storage/timescale/measurements.py identity arm).
--   * sleep_sessions is a plain table (BIGSERIAL PK) — its index stays
--     (owner_id, source_uuid).
--
-- Additive-only — no column is dropped or renamed; no existing unique index
-- is touched. Postgres >= 11 supports partial unique indexes with multiple
-- constraints on the same table; the floor is enforced by
-- db/migrations/012_canonical_observations.sql already in production.

BEGIN;

-- ─── heart_rate ──────────────────────────────────────────────────────
ALTER TABLE heart_rate
    ADD COLUMN IF NOT EXISTS source_uuid UUID;
ALTER TABLE heart_rate
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'heart_rate_status_check'
    ) THEN
        ALTER TABLE heart_rate
            ADD CONSTRAINT heart_rate_status_check
            CHECK (status IN ('active', 'superseded'));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_heart_rate_source_uuid
    ON heart_rate (owner_id, source_uuid, time)
    WHERE source_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_heart_rate_status_active
    ON heart_rate (owner_id, time DESC)
    WHERE status = 'active';

-- ─── hrv ─────────────────────────────────────────────────────────────
ALTER TABLE hrv
    ADD COLUMN IF NOT EXISTS source_uuid UUID;
ALTER TABLE hrv
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'hrv_status_check'
    ) THEN
        ALTER TABLE hrv
            ADD CONSTRAINT hrv_status_check
            CHECK (status IN ('active', 'superseded'));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_hrv_source_uuid
    ON hrv (owner_id, source_uuid, time)
    WHERE source_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hrv_status_active
    ON hrv (owner_id, time DESC)
    WHERE status = 'active';

-- ─── blood_oxygen ────────────────────────────────────────────────────
ALTER TABLE blood_oxygen
    ADD COLUMN IF NOT EXISTS source_uuid UUID;
ALTER TABLE blood_oxygen
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'blood_oxygen_status_check'
    ) THEN
        ALTER TABLE blood_oxygen
            ADD CONSTRAINT blood_oxygen_status_check
            CHECK (status IN ('active', 'superseded'));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_blood_oxygen_source_uuid
    ON blood_oxygen (owner_id, source_uuid, time)
    WHERE source_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blood_oxygen_status_active
    ON blood_oxygen (owner_id, time DESC)
    WHERE status = 'active';

-- ─── body_temperature ────────────────────────────────────────────────
ALTER TABLE body_temperature
    ADD COLUMN IF NOT EXISTS source_uuid UUID;
ALTER TABLE body_temperature
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'body_temperature_status_check'
    ) THEN
        ALTER TABLE body_temperature
            ADD CONSTRAINT body_temperature_status_check
            CHECK (status IN ('active', 'superseded'));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_body_temperature_source_uuid
    ON body_temperature (owner_id, source_uuid, time)
    WHERE source_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_body_temperature_status_active
    ON body_temperature (owner_id, time DESC)
    WHERE status = 'active';

-- ─── sleep_sessions ──────────────────────────────────────────────────
-- Sleep sessions are not a hypertable (BIGSERIAL PK); they identify via
-- (device_id, start_time, owner_id). The identity-aware revision path uses
-- source_uuid instead, which is what /api/v2/apple/batch will populate.
-- No `time` column here — plain tables may index any column set.
ALTER TABLE sleep_sessions
    ADD COLUMN IF NOT EXISTS source_uuid UUID;
ALTER TABLE sleep_sessions
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sleep_sessions_status_check'
    ) THEN
        ALTER TABLE sleep_sessions
            ADD CONSTRAINT sleep_sessions_status_check
            CHECK (status IN ('active', 'superseded'));
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sleep_sessions_source_uuid
    ON sleep_sessions (owner_id, source_uuid)
    WHERE source_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sleep_sessions_status_active
    ON sleep_sessions (owner_id, start_time DESC)
    WHERE status = 'active';

COMMIT;