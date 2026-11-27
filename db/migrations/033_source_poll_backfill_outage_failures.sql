-- 033_source_poll_backfill_outage_failures.sql
--
-- A second, more patient count of failed widened source polls.
--
-- 032 counts widened polls the vendor rejects (a 4xx about the range, a page
-- cap) and gives the wide window up after 3. A widened window that failed
-- with a server error, a timeout or a rate limit was never counted, so a
-- range the vendor could never serve was retried forever, and the default
-- window's data never arrived. The worker now asks for the default window in
-- the same run; when the vendor answers it, the wide range is at fault and the
-- failure is counted here, against a higher limit (12 polls, about 6 h on the
-- 30-minute cron). When the vendor answers neither, it is down and nothing is
-- counted, so an outage of any length keeps its backfill.
--
-- Additive only: one new column with a default; no row changes.
BEGIN;

ALTER TABLE source_poll_cursors
    ADD COLUMN IF NOT EXISTS backfill_outage_failures INTEGER NOT NULL DEFAULT 0;

COMMIT;
