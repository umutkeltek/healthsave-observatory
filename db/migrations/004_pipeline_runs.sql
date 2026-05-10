-- 004_pipeline_runs.sql
--
-- Pipeline runs ledger — one row per scheduled (or manually triggered)
-- job invocation. Decouples job state from APScheduler's in-memory
-- registry so a worker restart doesn't lose history, and gives manual
-- re-run / debug / observability a stable surface to query.
--
-- Distinct from analysis_runs (Phase 1.5):
--   * analysis_runs is engine-level (one row per analysis with LLM
--     token counts, period, etc.).
--   * pipeline_runs is scheduler-level (one row per worker job
--     invocation). A single pipeline_run may produce zero, one, or
--     many analysis_runs depending on what the job does.
--
-- Backward-compatible by construction (additive only):
--   * Existing analysis_runs / analysis_findings / analysis_insights
--     are unchanged.
--   * Existing scheduler behaviour is unchanged; recording is observer-
--     side via APScheduler event listeners, not a new dispatch path.

BEGIN;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    job_kind        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,

    -- Lifecycle
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')),
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,

    -- Outcome
    result          JSONB,
    error           TEXT,

    -- Lease (multi-worker scaling later; v2.0 single worker only)
    leased_by       TEXT,
    leased_at       TIMESTAMPTZ,
    lease_expires   TIMESTAMPTZ,

    -- Retry policy
    attempt         INTEGER NOT NULL DEFAULT 1,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ,

    -- Trigger origin
    triggered_by    TEXT NOT NULL DEFAULT 'scheduler'
        CHECK (triggered_by IN ('scheduler', 'manual', 'api', 'event')),

    -- Ownership / workspace (matches v2 contract pattern)
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',

    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Idempotency: jobs that produce the same idempotency_key are the
    -- same logical run. The unique constraint enforces this at the
    -- database layer; the application checks first to make
    -- already-run jobs surface as 'skipped' instead of failing.
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status_created
    ON pipeline_runs (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job_kind_created
    ON pipeline_runs (job_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_owner
    ON pipeline_runs (owner_id, workspace_id, created_at DESC);

-- Auto-update updated_at on every UPDATE.
CREATE OR REPLACE FUNCTION pipeline_runs_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pipeline_runs_updated_at ON pipeline_runs;
CREATE TRIGGER pipeline_runs_updated_at
    BEFORE UPDATE ON pipeline_runs
    FOR EACH ROW
    EXECUTE FUNCTION pipeline_runs_set_updated_at();

COMMIT;
