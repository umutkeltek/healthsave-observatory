-- Genotype originals are optional; immutable evidence reports remain private.
BEGIN;
CREATE TABLE IF NOT EXISTS genetic_documents (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    assembly TEXT NOT NULL CHECK (assembly IN ('GRCh37', 'GRCh38')),
    source_content BYTEA CHECK (source_content IS NULL OR octet_length(source_content) BETWEEN 1 AND 52428800),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_genetic_documents_owner_time
    ON genetic_documents(owner_id, workspace_id, created_at DESC);
CREATE TABLE IF NOT EXISTS genetic_reports (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES genetic_documents(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    reference_release TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    report JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_genetic_reports_document_time
    ON genetic_reports(document_id, created_at DESC);
COMMIT;
