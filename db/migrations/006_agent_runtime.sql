-- 006_agent_runtime.sql
--
-- Phase 7-A: AgentRun ledger tables for the v2 autonomy plane.
--
-- Mirrors the Pydantic types in ``packages/py/contracts/agents.py``:
--   AgentRun → agent_runs
--   AgentEvent → agent_events
--   ActionProposal → action_proposals
--   ActionDecision → action_decisions
--   ActionExecution → action_executions
--   AgentArtifact → agent_artifacts
--
-- Phase 7's agent supervisor (apps/agents/, lands in 7-C) writes to
-- these tables exclusively through ``packages/py/storage/timescale/
-- agents.py`` (Phase 7-B), keeping the storage zone seal intact.
--
-- Design notes:
--   * UUID primary keys via gen_random_uuid() — pgcrypto extension is
--     enabled at the top, idempotent.
--   * owner_id + workspace_id on EVERY table from day one (parent ISA
--     mandate). Pre-5G migrations 003/005 retrofitted the metric and
--     analysis tables; the v2 autonomy plane gets it natively.
--   * ON DELETE CASCADE down the (run_id, proposal_id, decision_id)
--     chain — an agent_run dropped takes its proposals, decisions,
--     executions, events, and artifacts with it. Audit history lives
--     in agent_events; a dropped run loses its event timeline too,
--     which is fine because the run row is the audit anchor.
--   * action_proposals.idempotency_key is nullable + partially-unique.
--     Phase 7-D's anomaly-watcher uses it to dedup proposals for the
--     same (plugin_id, finding_id) so a re-emit of a finding does not
--     create a duplicate Notify proposal. Proposals without an
--     idempotency_key are allowed (manual proposals, future kinds).
--   * Decision-by enum {user, policy, auto}: manual approvals bear
--     the user label; automated rule-based approvals bear policy;
--     the supervisor's own no-op auto-approval (rare; future-only)
--     bears auto.
--   * No hypertables: agent ledger rows are low-volume relative to
--     measurements. Phase 9+ may convert agent_events to a hypertable
--     when SSE-driven dashboards push event rates higher.
--
-- Apply with:
--   docker compose exec -T db psql -U healthsave -d healthsave \
--     < migrations/006_agent_runtime.sql

BEGIN;

-- Phase 7-A: server-side UUID generation. Idempotent if already present.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── agent_runs — one row per agent execution ──────────────────────
CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id       TEXT NOT NULL,

    -- Lifecycle
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,

    -- Trigger origin
    trigger_kind    TEXT NOT NULL
        CHECK (trigger_kind IN ('cron', 'ingest_event', 'metric_threshold', 'manual')),
    trigger_metadata JSONB NOT NULL DEFAULT '{}',

    -- Ownership
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',

    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_owner_started
    ON agent_runs (owner_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_plugin_started
    ON agent_runs (plugin_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_started
    ON agent_runs (status, started_at DESC);

-- ─── action_proposals — typed actions an agent wants to take ───────
CREATE TABLE IF NOT EXISTS action_proposals (
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

    -- Phase 7-D anomaly-watcher dedup: do not create duplicate Notify
    -- proposals for the same (plugin_id, finding_id). Nullable so
    -- non-dedup'd proposals (manual, future kinds) coexist.
    idempotency_key TEXT,

    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_action_proposals_idempotency_key
    ON action_proposals (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_action_proposals_owner_proposed
    ON action_proposals (owner_id, proposed_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_proposals_run
    ON action_proposals (run_id, proposed_at DESC);

-- ─── action_decisions — policy layer's verdict on a proposal ───────
CREATE TABLE IF NOT EXISTS action_decisions (
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

CREATE INDEX IF NOT EXISTS idx_action_decisions_owner_decided
    ON action_decisions (owner_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_decisions_proposal
    ON action_decisions (proposal_id);

-- ─── action_executions — outcome of running an approved proposal ───
CREATE TABLE IF NOT EXISTS action_executions (
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

CREATE INDEX IF NOT EXISTS idx_action_executions_owner_executed
    ON action_executions (owner_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_executions_proposal
    ON action_executions (proposal_id);

-- ─── agent_events — append-only timeline for SSE + audit ────────────
CREATE TABLE IF NOT EXISTS agent_events (
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

CREATE INDEX IF NOT EXISTS idx_agent_events_owner_emitted
    ON agent_events (owner_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_run_emitted
    ON agent_events (run_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_kind_emitted
    ON agent_events (kind, emitted_at DESC);

-- ─── agent_artifacts — persisted outputs (narrative, plan, chart) ──
CREATE TABLE IF NOT EXISTS agent_artifacts (
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

CREATE INDEX IF NOT EXISTS idx_agent_artifacts_owner_created
    ON agent_artifacts (owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_run_kind
    ON agent_artifacts (run_id, kind);

-- ─── updated_at trigger on agent_runs ──────────────────────────────
CREATE OR REPLACE FUNCTION agent_runs_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_runs_updated_at ON agent_runs;
CREATE TRIGGER agent_runs_updated_at
    BEFORE UPDATE ON agent_runs
    FOR EACH ROW
    EXECUTE FUNCTION agent_runs_set_updated_at();

COMMIT;
