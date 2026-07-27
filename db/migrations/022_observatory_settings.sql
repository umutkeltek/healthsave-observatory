-- 022_observatory_settings.sql
-- Person-local analytical calendar settings. Observation timestamps remain UTC;
-- these values only govern derived day/week/hour grouping and experiment dates.
BEGIN;

CREATE TABLE IF NOT EXISTS observatory_settings (
    owner_id                  UUID PRIMARY KEY
        DEFAULT '00000000-0000-0000-0000-000000000001',
    time_zone                 TEXT NOT NULL DEFAULT 'UTC',
    day_boundary_minutes      INTEGER NOT NULL DEFAULT 240
        CHECK (day_boundary_minutes BETWEEN 0 AND 720),
    revision                  BIGINT NOT NULL DEFAULT 1,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
