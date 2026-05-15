-- Add HealthSave sync receipts without changing the released v1 ingest contract.
-- The released iOS app already sends X-HealthSave-* headers; this table makes
-- them queryable for setup, support, and end-to-end receipt checks.

CREATE TABLE IF NOT EXISTS healthsave_sync_receipts (
    id                  BIGSERIAL PRIMARY KEY,
    sync_run_id         TEXT,
    batch_id            TEXT,
    payload_hash        TEXT,
    metric              TEXT NOT NULL,
    batch_index         INTEGER,
    total_batches       INTEGER,
    status              TEXT NOT NULL
        CHECK (status IN ('processed', 'empty', 'failed')),
    records_accepted    INTEGER NOT NULL DEFAULT 0,
    records_skipped     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    raw_log_id          BIGINT REFERENCES raw_ingestion_log(id),
    source_endpoint     TEXT NOT NULL DEFAULT '/api/apple/batch',
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_healthsave_sync_receipts_received_at
    ON healthsave_sync_receipts (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_healthsave_sync_receipts_run
    ON healthsave_sync_receipts (sync_run_id, batch_index);

CREATE UNIQUE INDEX IF NOT EXISTS uq_healthsave_sync_receipts_batch_id
    ON healthsave_sync_receipts (batch_id)
    WHERE batch_id IS NOT NULL;
