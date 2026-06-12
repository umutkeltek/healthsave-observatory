-- 019_medication_dose_events.sql
--
-- Additive HealthSave iOS medication event projection. The locked
-- /api/apple/batch route remains unchanged; iOS sends a new
-- medication_dose_event metric and this table stores the stateful
-- medication reminder/log rows separately from numeric quantity samples.

BEGIN;

CREATE TABLE IF NOT EXISTS medication_dose_events (
    time                    TIMESTAMPTZ NOT NULL,
    scheduled_time          TIMESTAMPTZ,
    device_id               INT REFERENCES devices(id),
    medication_metric       TEXT NOT NULL,
    medication_name         TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL,
    scheduled_dose_quantity DOUBLE PRECISION,
    dose_quantity           DOUBLE PRECISION,
    unit                    TEXT,
    source_id               TEXT,
    medication_concept_id   TEXT,
    owner_id                UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    PRIMARY KEY (time, device_id, medication_metric, owner_id)
);

SELECT create_hypertable('medication_dose_events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_medication_dose_events_status_time
    ON medication_dose_events (status, time DESC);

CREATE INDEX IF NOT EXISTS idx_medication_dose_events_metric_time
    ON medication_dose_events (medication_metric, time DESC);

COMMIT;
