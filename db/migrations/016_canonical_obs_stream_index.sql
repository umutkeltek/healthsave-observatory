-- 016_canonical_obs_stream_index.sql
--
-- Make per-stream (per-device) series reads fast. The v2 series endpoint now
-- accepts an optional stream_id filter
-- (see storage.timescale.observations._SERIES_SQL):
--
--   SELECT ... FROM canonical_observations
--    WHERE owner_id = :o AND workspace_id = :w AND metric_id = :m
--      AND interval_start >= :start AND interval_start < :end
--      AND status = 'active'
--      AND (CAST(:stream_id AS uuid) IS NULL OR stream_id = CAST(:stream_id AS uuid))
--    ORDER BY interval_start ASC;
--
-- stream_id is ALREADY written on ingest (normalization/apple.py), so this is a
-- read-path acceleration only — no data change, no backfill. This partial index
-- leads with the stream so a device-scoped series can run index-only, mirroring
-- the partial-index pattern of 012/014.
--
-- Additive + idempotent.

CREATE INDEX IF NOT EXISTS idx_canonical_obs_stream_time
    ON canonical_observations (owner_id, workspace_id, stream_id, interval_start DESC)
    WHERE status = 'active';
