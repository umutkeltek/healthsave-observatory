-- Private originals and immutable import receipts. Lab observations are written
-- only after an explicit review, in the same transaction as the receipt.
BEGIN;
CREATE TABLE IF NOT EXISTS lab_documents (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    file_name TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('text/csv', 'application/pdf')),
    sha256 TEXT NOT NULL,
    content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 5242880),
    extraction JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at TIMESTAMPTZ,
    review_sha256 TEXT,
    receipt JSONB,
    report JSONB,
    CHECK ((committed_at IS NULL AND receipt IS NULL AND report IS NULL)
        OR (committed_at IS NOT NULL AND receipt IS NOT NULL AND report IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_lab_documents_owner_time
    ON lab_documents (owner_id, workspace_id, created_at DESC);
COMMIT;
