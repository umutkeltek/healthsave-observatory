-- 028_lab_results.sql
--
-- Blood test results as a first-class source (Labs slice 1).
--
-- One row is one lab result: a LOINC-coded marker, its value in a UCUM
-- unit, the lab's OWN printed reference range, and the specimen time.
-- Columns mirror canonical_observations (metric_id, value_type,
-- numeric_value, canonical_unit, interval_start/end, source_id, stream_id,
-- dedup_key, semantic_key, quality_flags, provenance, normalizer_*,
-- status) so a later slice can project these rows into the canonical
-- store without reshaping them. Lab-only columns: value_comparator,
-- reference_low/high, reference_text, lab_name, panel.
--
-- Identity (docs/architecture/SOURCE_DEVICE_MODEL.md): source = the ingress
-- integration (labs-csv), device = the performing lab, stream = that lab
-- via that integration (deterministic uuid5). The panel is an attribute,
-- not identity.
--
-- Additive by construction:
--   * Brand-new table; nothing existing is touched.
--   * Plain table, not a hypertable: lab results are sparse (a few dozen
--     rows per blood draw), so partitioning buys nothing.
--   * Idempotent: CREATE ... IF NOT EXISTS; re-running is a no-op.
--   * Upserts converge on UNIQUE (owner_id, workspace_id, dedup_key).

BEGIN;

CREATE TABLE IF NOT EXISTS lab_results (
    id                  UUID PRIMARY KEY,
    owner_id            UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    workspace_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    metric_id           TEXT NOT NULL,
    loinc_code          TEXT NOT NULL,
    marker_name         TEXT,
    value_type          TEXT NOT NULL DEFAULT 'quantity'
                        CHECK (value_type IN ('quantity')),
    numeric_value       DOUBLE PRECISION NOT NULL,
    value_comparator    TEXT
                        CHECK (value_comparator IS NULL
                               OR value_comparator IN ('<', '<=', '>', '>=')),
    canonical_unit      TEXT NOT NULL,
    reference_low       DOUBLE PRECISION,
    reference_high      DOUBLE PRECISION,
    reference_text      TEXT,
    interval_start      TIMESTAMPTZ NOT NULL,
    interval_end        TIMESTAMPTZ NOT NULL,
    lab_name            TEXT NOT NULL,
    panel               TEXT,
    source_id           UUID NOT NULL,
    source_plugin_id    TEXT NOT NULL,
    stream_id           UUID NOT NULL,
    dedup_key           TEXT NOT NULL,
    semantic_key        TEXT,
    quality_flags       TEXT[] NOT NULL DEFAULT '{}',
    provenance          JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalizer_id       TEXT NOT NULL,
    normalizer_version  TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'superseded', 'rejected')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reference_low IS NULL OR reference_high IS NULL
           OR reference_low <= reference_high),
    UNIQUE (owner_id, workspace_id, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_lab_results_metric_time
    ON lab_results (owner_id, workspace_id, metric_id, interval_start DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_lab_results_stream_time
    ON lab_results (owner_id, workspace_id, stream_id, interval_start DESC);

COMMIT;
