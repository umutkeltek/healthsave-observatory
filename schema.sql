-- HealthSave Server Schema
-- Requires: PostgreSQL 16 + TimescaleDB extension

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─── Device Registry ─────────────────────────────────────────────────
CREATE TABLE devices (
    id              SERIAL PRIMARY KEY,
    device_type     TEXT NOT NULL UNIQUE,
    device_model    TEXT,
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Heart Rate ──────────────────────────────────────────────────────
CREATE TABLE heart_rate (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    source_id   TEXT,
    bpm         SMALLINT NOT NULL,
    context     TEXT
);
SELECT create_hypertable('heart_rate', 'time');
CREATE UNIQUE INDEX uq_heart_rate ON heart_rate (time, device_id);

-- ─── HRV ─────────────────────────────────────────────────────────────
CREATE TABLE hrv (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    source_id   TEXT,
    value_ms    FLOAT NOT NULL,
    algorithm   TEXT NOT NULL DEFAULT 'sdnn',
    context     TEXT
);
SELECT create_hypertable('hrv', 'time');
CREATE UNIQUE INDEX uq_hrv ON hrv (time, device_id);

-- ─── Blood Oxygen ────────────────────────────────────────────────────
CREATE TABLE blood_oxygen (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    spo2_pct    FLOAT NOT NULL,
    context     TEXT
);
SELECT create_hypertable('blood_oxygen', 'time');
CREATE UNIQUE INDEX uq_blood_oxygen ON blood_oxygen (time, device_id);

-- ─── Body Temperature ────────────────────────────────────────────────
CREATE TABLE body_temperature (
    time            TIMESTAMPTZ NOT NULL,
    device_id       INT REFERENCES devices(id),
    temp_celsius    FLOAT NOT NULL,
    measurement_type TEXT
);
SELECT create_hypertable('body_temperature', 'time');
CREATE UNIQUE INDEX uq_body_temperature ON body_temperature (time, device_id);

-- ─── Daily Activity ──────────────────────────────────────────────────
CREATE TABLE daily_activity (
    date            DATE NOT NULL,
    device_id       INT REFERENCES devices(id),
    steps           INT,
    distance_m      FLOAT,
    floors_climbed  INT,
    active_calories FLOAT,
    total_calories  FLOAT,
    active_minutes  INT,
    stand_hours     INT,
    avg_hr          FLOAT,
    max_hr          FLOAT,
    PRIMARY KEY (date, device_id)
);

-- ─── Sleep Sessions ──────────────────────────────────────────────────
CREATE TABLE sleep_sessions (
    id                  BIGSERIAL PRIMARY KEY,
    device_id           INT REFERENCES devices(id),
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    total_duration_ms   BIGINT,
    awake_ms            BIGINT,
    light_ms            BIGINT,
    deep_ms             BIGINT,
    rem_ms              BIGINT,
    respiratory_rate    FLOAT
);
CREATE UNIQUE INDEX uq_sleep_sessions_device_start ON sleep_sessions (device_id, start_time);

-- ─── Sleep Stages ────────────────────────────────────────────────────
CREATE TABLE sleep_stages (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    session_id  BIGINT REFERENCES sleep_sessions(id),
    stage       TEXT NOT NULL,
    duration_ms BIGINT
);
SELECT create_hypertable('sleep_stages', 'time');
CREATE UNIQUE INDEX uq_sleep_stages ON sleep_stages (time, device_id, stage);

-- ─── Workouts ────────────────────────────────────────────────────────
CREATE TABLE workouts (
    id              BIGSERIAL PRIMARY KEY,
    device_id       INT REFERENCES devices(id),
    sport_type      TEXT NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    duration_ms     BIGINT,
    avg_hr          FLOAT,
    max_hr          FLOAT,
    calories        FLOAT,
    distance_m      FLOAT
);
CREATE UNIQUE INDEX uq_workouts_device_start ON workouts (device_id, start_time);

-- ─── Recovery / Readiness ────────────────────────────────────────────
CREATE TABLE recovery (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    score       FLOAT,
    resting_hr  FLOAT,
    hrv_ms      FLOAT,
    spo2_pct    FLOAT,
    skin_temp_c FLOAT
);
SELECT create_hypertable('recovery', 'time');
CREATE UNIQUE INDEX uq_recovery ON recovery (time, device_id);

-- ─── Stress Readings ─────────────────────────────────────────────────
CREATE TABLE stress (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    score       FLOAT NOT NULL,
    scale_type  TEXT
);
SELECT create_hypertable('stress', 'time');
CREATE UNIQUE INDEX uq_stress ON stress (time, device_id);

-- ─── Raw Ingestion Log ───────────────────────────────────────────────
CREATE TABLE raw_ingestion_log (
    id          BIGSERIAL PRIMARY KEY,
    device_id   INT REFERENCES devices(id),
    source_type TEXT NOT NULL,
    endpoint    TEXT,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    raw_payload JSONB NOT NULL,
    processed   BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_raw_ingestion_log_ingested_at ON raw_ingestion_log (ingested_at DESC);

-- ─── Catch-all for any HealthKit metric ──────────────────────────────
CREATE TABLE quantity_samples (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    metric_name TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT,
    source_id   TEXT,
    PRIMARY KEY (time, device_id, metric_name)
);
SELECT create_hypertable('quantity_samples', 'time', if_not_exists => TRUE);
CREATE INDEX idx_quantity_samples_metric ON quantity_samples (metric_name, time DESC);

-- ─── Useful Continuous Aggregates ────────────────────────────────────

-- Hourly heart rate stats
CREATE MATERIALIZED VIEW hr_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    device_id,
    avg(bpm)::int AS avg_bpm,
    min(bpm) AS min_bpm,
    max(bpm) AS max_bpm,
    count(*) AS samples
FROM heart_rate
GROUP BY bucket, device_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('hr_hourly',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- Daily sleep summary
CREATE MATERIALIZED VIEW sleep_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    device_id,
    sum(duration_ms) FILTER (WHERE stage = 'deep') AS deep_ms,
    sum(duration_ms) FILTER (WHERE stage = 'rem') AS rem_ms,
    sum(duration_ms) FILTER (WHERE stage = 'light' OR stage = 'core') AS light_ms,
    sum(duration_ms) FILTER (WHERE stage = 'awake') AS awake_ms,
    sum(duration_ms) AS total_ms
FROM sleep_stages
GROUP BY bucket, device_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sleep_daily',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
