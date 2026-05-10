-- Adds the storage tables used by the Phase 1 AI analytics pivot.
-- Additive only: no DROP, no ALTER on pre-existing tables. Safe to run on
-- existing installs before the analysis engine is actually wired up.
--
-- Apply with:
--   docker compose exec -T db psql -U healthsave -d healthsave \
--     < migrations/002_analysis_tables.sql

CREATE TABLE IF NOT EXISTS analysis_runs (
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
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS analysis_findings (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    finding_type    TEXT NOT NULL,
    metric          TEXT,
    severity        TEXT
        CHECK (severity IN ('info', 'watch', 'alert')),
    structured_data JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_insights (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    insight_type    TEXT NOT NULL,
    narrative       TEXT NOT NULL,
    findings_used   BIGINT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_insights_type_created
    ON analysis_insights (insight_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_run
    ON analysis_findings (run_id);
CREATE INDEX IF NOT EXISTS idx_runs_type_status
    ON analysis_runs (run_type, status);
