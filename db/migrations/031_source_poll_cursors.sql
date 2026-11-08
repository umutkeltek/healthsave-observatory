-- 031_source_poll_cursors.sql
--
-- Per-provider, per-owner "last successful poll" cursor for source plugins
-- (Whoop, Amazfit, Polar, Google Health).
--
-- Each poll fetched a fixed window ("now minus 1 day" or "now minus 7
-- days") and nothing recorded when a poll last succeeded, so an outage
-- longer than that window (a dead token, the vendor down, the worker
-- stopped) left a permanent gap. The worker reads this cursor to widen the
-- next window back to the last success (bounded in apps/worker), and moves
-- it forward only in the same transaction that commits the poll's data.
--
-- Additive only: one new table; no existing object is touched.
BEGIN;

CREATE TABLE IF NOT EXISTS source_poll_cursors (
    owner_id        UUID NOT NULL,
    provider        TEXT NOT NULL,
    last_success_at TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (owner_id, provider)
);

COMMIT;
