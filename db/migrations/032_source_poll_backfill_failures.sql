-- 032_source_poll_backfill_failures.sql
--
-- Bound the source-poll backfill from 031.
--
-- After an outage the worker widens a poll's window back to the last
-- successful poll. If that wide window keeps failing (a vendor page cap, a
-- range the vendor rejects), the cursor never moves and every poll would
-- retry the same wide window forever. The worker counts failed widened
-- polls here and, after a few, polls the default window again. The gap it
-- gives up on is recorded so it stays visible.
--
-- Additive only: three new columns with defaults; no row changes.
BEGIN;

ALTER TABLE source_poll_cursors
    ADD COLUMN IF NOT EXISTS backfill_failures INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unfilled_gap_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS unfilled_gap_end TIMESTAMPTZ;

COMMIT;
