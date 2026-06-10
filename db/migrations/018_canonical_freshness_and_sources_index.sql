-- 018_canonical_freshness_and_sources_index.sql
--
-- Two index-assisted reads for the v2 dashboard surfaces (live store is 2M+
-- rows; both reads degraded to multi-second scans):
--
-- 1. The change fingerprint (/api/v2/changes, polled ~30s by the dashboard)
--    now reads a single freshness scalar
--    (storage.timescale.analysis.fetch_last_ingested_at):
--
--      SELECT max(created_at) FROM canonical_observations
--       WHERE owner_id = :o AND workspace_id = :w AND status = 'active';
--
--    Without an index this is a full scan per poll. The partial index below
--    makes it a reverse index walk.
--
-- 2. The source-attribution aggregate
--    (storage.timescale.analysis.fetch_canonical_sources):
--
--      SELECT provenance->>'source_plugin_id', count(*), max(created_at)
--        FROM canonical_observations
--       WHERE owner_id = :o AND workspace_id = :w AND status = 'active'
--       GROUP BY 1;
--
--    The expression index lets the aggregate run index-only (no heap fetch,
--    no per-row JSONB parse). It is also SWR-cached server-side now, so this
--    index mostly speeds up the once-per-TTL refresh.
--
-- Additive + idempotent; no data change.

CREATE INDEX IF NOT EXISTS idx_canonical_obs_freshness
    ON canonical_observations (owner_id, workspace_id, created_at)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_canonical_obs_source_plugin
    ON canonical_observations (owner_id, workspace_id, (provenance->>'source_plugin_id'), created_at)
    WHERE status = 'active';
