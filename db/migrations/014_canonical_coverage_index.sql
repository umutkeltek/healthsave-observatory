-- 014_canonical_coverage_index.sql
--
-- Speed up the data-readiness coverage aggregate. The readiness card runs
-- (see storage.timescale.analysis.fetch_canonical_coverage):
--
--   SELECT metric_id, count(*), count(DISTINCT date_trunc('day', interval_start)),
--          min(interval_start), max(interval_start), max(created_at)
--     FROM canonical_observations
--    WHERE owner_id = :o AND workspace_id = :w AND status = 'active'
--    GROUP BY metric_id;
--
-- The existing idx_canonical_obs_metric_time omits created_at, so max(created_at)
-- forced a heap fetch per row — at multi-million-row scale the whole aggregate
-- degraded into a ~30s heap scan. This partial covering index carries every
-- column the query touches (metric_id for the grouping, interval_start for the
-- count/distinct-day/min/max, created_at for the ingest max), filtered to the
-- active rows the query selects, so it can run index-only.
--
-- Additive + idempotent; no data change.

CREATE INDEX IF NOT EXISTS idx_canonical_obs_coverage
    ON canonical_observations (owner_id, workspace_id, metric_id, interval_start, created_at)
    WHERE status = 'active';
