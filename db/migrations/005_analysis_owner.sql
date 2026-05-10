-- 005_analysis_owner.sql
--
-- Phase 5G-A retrofit: add owner_id + workspace_id to the analysis-side
-- ledger tables (analysis_runs / analysis_findings / analysis_insights).
--
-- Why now: migration 003 added owner_id to every metric table so two
-- residents can ingest into the same stack without colliding, but it
-- skipped the analysis tables. The audit (Phase 5G) caught the
-- asymmetry — the v2 ownership invariant (every record carries
-- owner_id + workspace_id) lives at the data layer but not at the
-- analysis layer.
--
-- Backward-compatible by construction (same shape as 003):
--   * Both columns are NOT NULL with the single-user sentinel default
--     '00000000-0000-0000-0000-000000000001'. Existing rows are
--     populated automatically.
--   * Engine code does NOT change in this migration — INSERTs that
--     don't specify owner_id / workspace_id get the sentinel via
--     column default. Single-user installs keep working unchanged.
--   * Phase 7+ analysis-side multi-tenancy work (when the agent
--     runtime owns its runs per-user) can start passing explicit
--     owner_id without another migration.
--
-- Why workspace_id too: parent ISA decision 2026-05-10T15:10:00Z
-- — owner_id + workspace_id from day one. The metric tables only
-- got owner_id (workspace_id was deferred); this migration adds
-- BOTH to the analysis tables since we're touching them anyway. A
-- future migration 006 can backfill workspace_id on the metric
-- tables.
--
-- Apply with:
--   docker compose exec -T db psql -U healthsave -d healthsave \
--     < migrations/005_analysis_owner.sql

BEGIN;

ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS workspace_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';

ALTER TABLE analysis_findings
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE analysis_findings
    ADD COLUMN IF NOT EXISTS workspace_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';

ALTER TABLE analysis_insights
    ADD COLUMN IF NOT EXISTS owner_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE analysis_insights
    ADD COLUMN IF NOT EXISTS workspace_id UUID NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';

-- Helpful indexes for the per-owner read patterns the dashboard will
-- want once multi-tenant analysis lands. Cheap to create now; the
-- alternative is creating them under load later.
CREATE INDEX IF NOT EXISTS idx_runs_owner_started
    ON analysis_runs (owner_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_owner_created
    ON analysis_findings (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_insights_owner_type_created
    ON analysis_insights (owner_id, insight_type, created_at DESC);

COMMIT;
