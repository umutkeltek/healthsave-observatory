-- 013_experiments.sql
--
-- The n-of-1 experiment engine (roadmap: the deferred ExperimentRepository,
-- now built). Turns a ranked correlation candidate into a committed ABAB
-- experiment and stores the analysis the runtime computes against it.
--
-- Additive by construction:
--   * Two brand-new tables — no existing table/column/PK touched, so the locked
--     v1 iOS contract and every prior table are unaffected.
--   * owner_id / workspace_id default to the single-user sentinel (matching
--     canonical_observations + the agent ledger), so a self-hosted install
--     writes here with no auth coordination.
--   * experiment_results.experiment_id CASCADEs — dropping an experiment takes
--     its computed results with it.
--
-- Two result `kind`s: 'retrospective' (the instant observational read over
-- existing history, median-split on the lever) and 'controlled' (the ABAB
-- result once the window has run). The detailed stats payload (means, n,
-- block count, adherence, caveat) lives in structured_data JSONB; the columns
-- promoted out of it (direction/diff/effect_size/p_value/inference) are the
-- ones the dashboard sorts and badges on.
--
-- Apply with:
--   docker compose exec -T db psql -U healthsave -d healthsave \
--     < migrations/013_experiments.sql

BEGIN;

-- Server-side UUID generation. Idempotent if already enabled (006 did).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

COMMIT;
