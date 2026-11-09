-- 034_fusion_rejected_pair_index.sql
--
-- Index the lookup that keeps a rejected fusion pair from being decided again.
--
-- The session-fusion candidate query now skips a pair the matcher already
-- rejected while neither row has changed (NOT EXISTS on fusion_decisions by
-- owner and the pair's two observation ids). Until now every poll appended
-- another 'rejected' row for such a pair, so an install that ran for a while
-- can hold many of them; without this index the check scans them all on
-- every poll.
--
-- Additive only: one partial index; no row changes.
BEGIN;

CREATE INDEX IF NOT EXISTS idx_fusion_decisions_rejected_pair
    ON fusion_decisions (owner_id, variant_observation_ids)
    WHERE decision = 'rejected';

COMMIT;
