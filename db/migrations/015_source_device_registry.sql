-- 015_source_device_registry.sql
--
-- R2 Track A — Source / Device / Stream identity foundation (minimal slice).
-- See docs/architecture/SOURCE_DEVICE_MODEL.md.
--
-- Additive by construction (the additive-migrations rule):
--   * Two brand-new registry tables — nothing existing is touched.
--   * One nullable column on canonical_observations (metadata-only on the
--     hypertable; no row rewrite, safe on the live 2.96M-row table).
--   * Idempotent: CREATE TABLE / ADD COLUMN IF NOT EXISTS — safe to re-run.
--
-- Model:
--   * sources                = the integration data entered through
--                              (apple-healthkit-ios, whoop-oauth, ...).
--   * source_device_streams  = the join "this device via this integration",
--                              keyed by a STABLE deterministic uuid5 (the
--                              resolver in normalization.identity). HA entities
--                              key on this id. The same band via HealthKit vs a
--                              direct poll = two streams.
--   * canonical_observations.stream_id = the stream a canonical row belongs to
--                              (dual-written on ingest in a later stage; nullable
--                              so existing rows and the frozen path are untouched).

BEGIN;

CREATE TABLE IF NOT EXISTS sources (
    id            UUID PRIMARY KEY,
    owner_id      UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    plugin_id     TEXT NOT NULL,
    display_name  TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, plugin_id)
);

CREATE TABLE IF NOT EXISTS source_device_streams (
    id               UUID PRIMARY KEY,  -- deterministic uuid5(owner, plugin, origin)
    owner_id         UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    source_plugin_id TEXT NOT NULL,
    origin_key       TEXT NOT NULL,
    device_label     TEXT,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, source_plugin_id, origin_key)
);

CREATE INDEX IF NOT EXISTS idx_streams_owner_plugin
    ON source_device_streams (owner_id, source_plugin_id);

ALTER TABLE canonical_observations
    ADD COLUMN IF NOT EXISTS stream_id UUID;

COMMIT;
