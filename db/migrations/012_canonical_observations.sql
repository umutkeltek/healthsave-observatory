-- 012_canonical_observations.sql
--
-- The v2 canonical Observation store (Decision C: canonical-observation
-- table is truth; the per-metric v1 tables become projections later).
-- Every source plugin normalizes into this one device-agnostic shape; the
-- read API and the LLM narrator both query it.
--
-- Additive by construction:
--   * Brand-new table — no existing table/column/PK touched, so the locked
--     v1 iOS contract and the per-metric hypertables are unaffected.
--   * owner_id / workspace_id default to the single-user sentinel, so a
--     self-hosted install writes here with no auth coordination.
--   * Idempotency is the unique (owner, workspace, dedup_key, interval_start)
--     index — re-ingest and replay converge on the same row. The partition
--     column (interval_start) is included because Timescale requires it in
--     every unique index on a hypertable.
--   * No PRIMARY KEY: a hypertable cannot have a PK that omits the partition
--     column; the dedup unique index carries the integrity guarantee instead.
--   * Polymorphic value: numeric_value (quantity) | code (categorical) |
--     components (JSONB) | value_json (event/json/waveform), tagged by
--     value_type. Hot scalar reads stay on the indexed numeric_value column.

BEGIN;

CREATE TABLE IF NOT EXISTS canonical_observations (
    id                  UUID        NOT NULL,
    owner_id            UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id        UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    metric_id           TEXT        NOT NULL,
    ontology_version    TEXT        NOT NULL,
    value_type          TEXT        NOT NULL,
    numeric_value       DOUBLE PRECISION,
    canonical_unit      TEXT,
    code                TEXT,
    components          JSONB,
    value_json          JSONB,
    interval_start      TIMESTAMPTZ NOT NULL,
    interval_end        TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ,
    source_id           UUID        NOT NULL,
    device_id           UUID,
    raw_payload_id      UUID,
    source_record_uid   TEXT,
    confidence          DOUBLE PRECISION,
    quality_flags       TEXT[]      NOT NULL DEFAULT '{}',
    provenance          JSONB       NOT NULL,
    normalizer_id       TEXT        NOT NULL,
    normalizer_version  TEXT        NOT NULL,
    normalization_run_id UUID,
    dedup_key           TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'superseded', 'rejected')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable('canonical_observations', 'interval_start', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_obs_dedup
    ON canonical_observations (owner_id, workspace_id, dedup_key, interval_start);

CREATE INDEX IF NOT EXISTS idx_canonical_obs_metric_time
    ON canonical_observations (owner_id, workspace_id, metric_id, interval_start DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_canonical_obs_source_time
    ON canonical_observations (owner_id, workspace_id, source_id, interval_start DESC);

COMMIT;
