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
    context     TEXT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('heart_rate', 'time');
CREATE UNIQUE INDEX uq_heart_rate ON heart_rate (time, device_id, owner_id);

-- ─── HRV ─────────────────────────────────────────────────────────────
CREATE TABLE hrv (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    source_id   TEXT,
    value_ms    FLOAT NOT NULL,
    algorithm   TEXT NOT NULL DEFAULT 'sdnn',
    context     TEXT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('hrv', 'time');
CREATE UNIQUE INDEX uq_hrv ON hrv (time, device_id, owner_id);

-- ─── Blood Oxygen ────────────────────────────────────────────────────
CREATE TABLE blood_oxygen (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    spo2_pct    FLOAT NOT NULL,
    context     TEXT,
    source_id   TEXT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('blood_oxygen', 'time');
CREATE UNIQUE INDEX uq_blood_oxygen ON blood_oxygen (time, device_id, owner_id);
CREATE INDEX idx_blood_oxygen_source_time
    ON blood_oxygen (source_id, time DESC)
    WHERE source_id IS NOT NULL;

-- ─── Body Temperature ────────────────────────────────────────────────
CREATE TABLE body_temperature (
    time            TIMESTAMPTZ NOT NULL,
    device_id       INT REFERENCES devices(id),
    temp_celsius    FLOAT NOT NULL,
    measurement_type TEXT,
    source_id       TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('body_temperature', 'time');
CREATE UNIQUE INDEX uq_body_temperature ON body_temperature (time, device_id, owner_id);
CREATE INDEX idx_body_temperature_source_time
    ON body_temperature (source_id, time DESC)
    WHERE source_id IS NOT NULL;

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
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    source_id       TEXT,
    PRIMARY KEY (date, device_id, owner_id)
);
CREATE INDEX idx_daily_activity_source_date
    ON daily_activity (source_id, date DESC)
    WHERE source_id IS NOT NULL;

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
    respiratory_rate    FLOAT,
    owner_id            UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    source_id           TEXT
);
CREATE UNIQUE INDEX uq_sleep_sessions_device_start
    ON sleep_sessions (device_id, start_time, owner_id);
CREATE INDEX idx_sleep_sessions_source_start
    ON sleep_sessions (source_id, start_time DESC)
    WHERE source_id IS NOT NULL;

-- ─── Sleep Stages ────────────────────────────────────────────────────
CREATE TABLE sleep_stages (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    session_id  BIGINT REFERENCES sleep_sessions(id),
    stage       TEXT NOT NULL,
    duration_ms BIGINT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('sleep_stages', 'time');
CREATE UNIQUE INDEX uq_sleep_stages ON sleep_stages (time, device_id, stage, owner_id);

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
    distance_m      FLOAT,
    source_id       TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE UNIQUE INDEX uq_workouts_device_start
    ON workouts (device_id, start_time, owner_id);
CREATE INDEX idx_workouts_source_start
    ON workouts (source_id, start_time DESC)
    WHERE source_id IS NOT NULL;

-- ─── Recovery / Readiness ────────────────────────────────────────────
CREATE TABLE recovery (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    score       FLOAT,
    resting_hr  FLOAT,
    hrv_ms      FLOAT,
    spo2_pct    FLOAT,
    skin_temp_c FLOAT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('recovery', 'time');
CREATE UNIQUE INDEX uq_recovery ON recovery (time, device_id, owner_id);

-- ─── Stress Readings ─────────────────────────────────────────────────
CREATE TABLE stress (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    score       FLOAT NOT NULL,
    scale_type  TEXT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
SELECT create_hypertable('stress', 'time');
CREATE UNIQUE INDEX uq_stress ON stress (time, device_id, owner_id);

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

-- ─── HealthSave Sync Receipts ────────────────────────────────────────
-- Additive v2 operator trail fed by headers the released iOS app already sends.
CREATE TABLE healthsave_sync_receipts (
    id                  BIGSERIAL PRIMARY KEY,
    sync_run_id         TEXT,
    batch_id            TEXT,
    idempotency_key     TEXT,
    payload_hash        TEXT,
    metric              TEXT NOT NULL,
    batch_index         INTEGER,
    total_batches       INTEGER,
    sync_mode           TEXT,
    anchor_present      BOOLEAN,
    lower_bound_reason  TEXT,
    full_export         BOOLEAN,
    query_lower_bound_at TIMESTAMPTZ,
    status              TEXT NOT NULL
        CHECK (status IN ('processed', 'empty', 'failed')),
    records_received    INTEGER NOT NULL DEFAULT 0,
    records_accepted    INTEGER NOT NULL DEFAULT 0,
    -- DOMAIN-002: records_skipped == genuine validation REJECTIONS only. It is
    -- NOT aggregation rollup (sleep stages -> sessions) and NOT in-batch dedupe.
    -- Deriving it as (received - accepted) once reported ~95% of a healthy sleep
    -- sync as "skipped" -- see tests/test_honest_sync_accounting.py before
    -- changing the semantics (the wire field is records_rejected).
    records_skipped     INTEGER NOT NULL DEFAULT 0,
    records_inserted_new INTEGER,
    records_deduped_existing INTEGER,
    storage_result_level TEXT NOT NULL DEFAULT 'accepted_only',
    sample_min_at       TIMESTAMPTZ,
    sample_max_at       TIMESTAMPTZ,
    error_message       TEXT,
    raw_log_id          BIGINT REFERENCES raw_ingestion_log(id),
    source_endpoint     TEXT NOT NULL DEFAULT '/api/apple/batch',
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);
CREATE INDEX idx_healthsave_sync_receipts_received_at
    ON healthsave_sync_receipts (received_at DESC);
CREATE INDEX idx_healthsave_sync_receipts_run
    ON healthsave_sync_receipts (sync_run_id, batch_index);
CREATE UNIQUE INDEX uq_healthsave_sync_receipts_batch_id
    ON healthsave_sync_receipts (batch_id)
    WHERE batch_id IS NOT NULL;
CREATE UNIQUE INDEX uq_healthsave_sync_receipts_idempotency_key
    ON healthsave_sync_receipts (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- ─── Catch-all for any HealthKit metric ──────────────────────────────
CREATE TABLE quantity_samples (
    time        TIMESTAMPTZ NOT NULL,
    device_id   INT REFERENCES devices(id),
    metric_name TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT,
    source_id   TEXT,
    owner_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    PRIMARY KEY (time, device_id, metric_name, owner_id)
);
SELECT create_hypertable('quantity_samples', 'time', if_not_exists => TRUE);
CREATE INDEX idx_quantity_samples_metric ON quantity_samples (metric_name, time DESC);

-- ─── Medication dose events ─────────────────────────────────────────
CREATE TABLE medication_dose_events (
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
CREATE INDEX idx_medication_dose_events_status_time
    ON medication_dose_events (status, time DESC);
CREATE INDEX idx_medication_dose_events_metric_time
    ON medication_dose_events (medication_metric, time DESC);

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

-- ─── Phase 1.5 Analysis Tables ────────────────────────────────────────
-- owner_id + workspace_id added by Phase 5G (migration 005). Fresh
-- installs get them here with the single-user sentinel default; the
-- migration handles upgrades.
CREATE TABLE analysis_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_type        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'skipped')),
    period_start    DATE,
    period_end      DATE,
    llm_provider    TEXT,
    llm_tokens_in   INTEGER,
    llm_tokens_out  INTEGER,
    error_message   TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);

CREATE TABLE analysis_findings (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    finding_type    TEXT NOT NULL,
    metric          TEXT,
    severity        TEXT
        CHECK (severity IN ('info', 'watch', 'alert')),
    structured_data JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);

CREATE TABLE analysis_insights (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    insight_type    TEXT NOT NULL,
    narrative       TEXT NOT NULL,
    findings_used   BIGINT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);

CREATE INDEX idx_insights_type_created
    ON analysis_insights (insight_type, created_at DESC);
CREATE INDEX idx_findings_run
    ON analysis_findings (run_id);
CREATE INDEX idx_runs_type_status
    ON analysis_runs (run_type, status);
CREATE INDEX idx_runs_owner_started
    ON analysis_runs (owner_id, started_at DESC);
CREATE INDEX idx_findings_owner_created
    ON analysis_findings (owner_id, created_at DESC);
CREATE INDEX idx_insights_owner_type_created
    ON analysis_insights (owner_id, insight_type, created_at DESC);

-- Pipeline runs ledger (Phase 4B): one row per scheduled or manual job
-- invocation. See db/migrations/004_pipeline_runs.sql for the upgrade
-- path on existing installs.
CREATE TABLE pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    job_kind        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')),
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    result          JSONB,
    error           TEXT,
    leased_by       TEXT,
    leased_at       TIMESTAMPTZ,
    lease_expires   TIMESTAMPTZ,
    attempt         INTEGER NOT NULL DEFAULT 1,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ,
    triggered_by    TEXT NOT NULL DEFAULT 'scheduler'
        CHECK (triggered_by IN ('scheduler', 'manual', 'api', 'event')),
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (idempotency_key)
);

CREATE INDEX idx_pipeline_runs_status_created
    ON pipeline_runs (status, created_at DESC);
CREATE INDEX idx_pipeline_runs_job_kind_created
    ON pipeline_runs (job_kind, created_at DESC);
CREATE INDEX idx_pipeline_runs_owner
    ON pipeline_runs (owner_id, workspace_id, created_at DESC);

CREATE OR REPLACE FUNCTION pipeline_runs_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pipeline_runs_updated_at
    BEFORE UPDATE ON pipeline_runs
    FOR EACH ROW
    EXECUTE FUNCTION pipeline_runs_set_updated_at();

-- ─── Phase 7-A: AgentRun ledger ──────────────────────────────────────
-- See db/migrations/006_agent_runtime.sql for the upgrade path on
-- existing installs. Mirrors packages/py/contracts/agents.py. All
-- tables carry owner_id + workspace_id from day one (parent ISA
-- mandate). UUID PKs via pgcrypto (idempotent extension).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE agent_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    trigger_kind    TEXT NOT NULL
        CHECK (trigger_kind IN ('cron', 'ingest_event', 'metric_threshold', 'manual')),
    trigger_metadata JSONB NOT NULL DEFAULT '{}',
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_runs_owner_started
    ON agent_runs (owner_id, started_at DESC);
CREATE INDEX idx_agent_runs_plugin_started
    ON agent_runs (plugin_id, started_at DESC);
CREATE INDEX idx_agent_runs_status_started
    ON agent_runs (status, started_at DESC);

CREATE TABLE action_proposals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    proposed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_kind     TEXT NOT NULL
        CHECK (action_kind IN (
            'notify',
            'create_experiment',
            'create_briefing',
            'request_user_input',
            'tag_measurement'
        )),
    payload         JSONB NOT NULL DEFAULT '{}',
    rationale       TEXT NOT NULL,
    capability      TEXT NOT NULL,
    idempotency_key TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_action_proposals_idempotency_key
    ON action_proposals (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_action_proposals_owner_proposed
    ON action_proposals (owner_id, proposed_at DESC);
CREATE INDEX idx_action_proposals_run
    ON action_proposals (run_id, proposed_at DESC);

CREATE TABLE action_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     UUID NOT NULL REFERENCES action_proposals(id) ON DELETE CASCADE,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision        TEXT NOT NULL
        CHECK (decision IN ('approved', 'rejected', 'deferred')),
    decided_by      TEXT NOT NULL
        CHECK (decided_by IN ('user', 'policy', 'auto')),
    rationale       TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_action_decisions_owner_decided
    ON action_decisions (owner_id, decided_at DESC);
CREATE INDEX idx_action_decisions_proposal
    ON action_decisions (proposal_id);

CREATE TABLE action_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     UUID NOT NULL REFERENCES action_proposals(id) ON DELETE CASCADE,
    decision_id     UUID NOT NULL REFERENCES action_decisions(id) ON DELETE CASCADE,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL
        CHECK (status IN ('succeeded', 'failed', 'skipped')),
    result          JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_action_executions_owner_executed
    ON action_executions (owner_id, executed_at DESC);
CREATE INDEX idx_action_executions_proposal
    ON action_executions (proposal_id);

CREATE TABLE agent_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    emitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind            TEXT NOT NULL
        CHECK (kind IN (
            'run_started',
            'run_completed',
            'run_failed',
            'observation',
            'proposal_created',
            'proposal_approved',
            'proposal_rejected',
            'execution_succeeded',
            'execution_failed',
            'artifact_created'
        )),
    payload         JSONB NOT NULL DEFAULT '{}',
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_events_owner_emitted
    ON agent_events (owner_id, emitted_at DESC);
CREATE INDEX idx_agent_events_run_emitted
    ON agent_events (run_id, emitted_at DESC);
CREATE INDEX idx_agent_events_kind_emitted
    ON agent_events (kind, emitted_at DESC);

CREATE TABLE agent_artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL
        CHECK (kind IN (
            'narrative',
            'chart_spec',
            'experiment_plan',
            'intervention_proposal'
        )),
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE INDEX idx_agent_artifacts_owner_created
    ON agent_artifacts (owner_id, created_at DESC);
CREATE INDEX idx_agent_artifacts_run_kind
    ON agent_artifacts (run_id, kind);

CREATE OR REPLACE FUNCTION agent_runs_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agent_runs_updated_at
    BEFORE UPDATE ON agent_runs
    FOR EACH ROW
    EXECUTE FUNCTION agent_runs_set_updated_at();

-- ─── n-of-1 experiment engine (migration 013) ──────────────────────
-- Committed ABAB experiments + the analysis the runtime computes against
-- them. owner_id/workspace_id default to the single-user sentinel.
CREATE TABLE IF NOT EXISTS experiments (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id           UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    lever_metric_id    TEXT NOT NULL,
    outcome_metric_id  TEXT NOT NULL,
    design             TEXT NOT NULL DEFAULT 'ABAB',
    block_days         INTEGER NOT NULL DEFAULT 7 CHECK (block_days BETWEEN 1 AND 90),
    start_date         DATE NOT NULL,
    hypothesis         TEXT,
    status             TEXT NOT NULL DEFAULT 'collecting'
                       CHECK (status IN ('collecting', 'completed', 'abandoned')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id      UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    owner_id           UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id       UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    kind               TEXT NOT NULL DEFAULT 'controlled'
                       CHECK (kind IN ('retrospective', 'controlled')),
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    direction          TEXT,
    diff               DOUBLE PRECISION,
    effect_size        DOUBLE PRECISION,
    p_value            DOUBLE PRECISION,
    inference          TEXT,
    summary            TEXT,
    structured_data    JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiments_owner_status
    ON experiments (owner_id, workspace_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiment_results_experiment
    ON experiment_results (experiment_id, computed_at DESC);
