-- Add stronger HealthSave receipt evidence for build 1.5 Server Sync debugging.
-- This migration is additive so already-deployed Data Hub instances can prove
-- idempotency, sample windows, and delivery-vs-sample freshness separately.

ALTER TABLE healthsave_sync_receipts
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS sync_mode TEXT,
    ADD COLUMN IF NOT EXISTS anchor_present BOOLEAN,
    ADD COLUMN IF NOT EXISTS lower_bound_reason TEXT,
    ADD COLUMN IF NOT EXISTS full_export BOOLEAN,
    ADD COLUMN IF NOT EXISTS query_lower_bound_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS records_received INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS records_inserted_new INTEGER,
    ADD COLUMN IF NOT EXISTS records_deduped_existing INTEGER,
    ADD COLUMN IF NOT EXISTS storage_result_level TEXT NOT NULL DEFAULT 'accepted_only',
    ADD COLUMN IF NOT EXISTS sample_min_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sample_max_at TIMESTAMPTZ;

UPDATE healthsave_sync_receipts
SET idempotency_key = batch_id
WHERE idempotency_key IS NULL
  AND batch_id IS NOT NULL;

UPDATE healthsave_sync_receipts
SET records_received = records_accepted + records_skipped
WHERE records_received = 0
  AND (records_accepted > 0 OR records_skipped > 0);

CREATE UNIQUE INDEX IF NOT EXISTS uq_healthsave_sync_receipts_idempotency_key
    ON healthsave_sync_receipts (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
