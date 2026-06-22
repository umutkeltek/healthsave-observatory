-- 020_canonical_fusion_metadata.sql
--
-- Additive fusion metadata for direct vendor connector + Health Connect relay
-- reconciliation. The canonical row remains the raw stream observation; fusion is
-- a reversible read-time assertion recorded by semantic_key + audit rows.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE canonical_observations
ADD COLUMN IF NOT EXISTS exact_ingest_key TEXT,
ADD COLUMN IF NOT EXISTS semantic_key TEXT,
ADD COLUMN IF NOT EXISTS semantic_key_version TEXT,
ADD COLUMN IF NOT EXISTS aggregation_scope TEXT NOT NULL DEFAULT 'interval_component',
ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT TRUE;

DO $$
BEGIN
    ALTER TABLE canonical_observations
    ADD CONSTRAINT chk_canonical_obs_aggregation_scope
    CHECK (
        aggregation_scope IN (
            'interval_component',
            'device_day_total',
            'provider_account_day_total',
            'provider_reconciled_day_total',
            'owner_all_source_day_total'
        )
    );
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

CREATE TABLE IF NOT EXISTS fusion_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    semantic_key TEXT NOT NULL,
    semantic_key_version TEXT NOT NULL,
    matcher_id TEXT NOT NULL,
    matcher_version TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('assigned', 'rejected', 'revoked')),
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    primary_observation_id UUID,
    variant_observation_ids UUID[] NOT NULL DEFAULT '{}',
    decided_by TEXT NOT NULL DEFAULT 'system',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_identity_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    direct_stream_id UUID NOT NULL,
    relayed_stream_id UUID NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'confirmed', 'rejected', 'expired')),
    confidence TEXT NOT NULL CHECK (confidence IN ('none', 'weak', 'medium', 'strong')),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, direct_stream_id, relayed_stream_id)
);

CREATE INDEX IF NOT EXISTS idx_canonical_obs_semantic_key
    ON canonical_observations (owner_id, workspace_id, semantic_key)
    WHERE semantic_key IS NOT NULL AND status = 'active';

CREATE INDEX IF NOT EXISTS idx_canonical_obs_exact_ingest_key
    ON canonical_observations (owner_id, workspace_id, exact_ingest_key)
    WHERE exact_ingest_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fusion_decisions_semantic_key
    ON fusion_decisions (owner_id, workspace_id, semantic_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_device_identity_links_streams
    ON device_identity_links (owner_id, direct_stream_id, relayed_stream_id, status);

COMMIT;
