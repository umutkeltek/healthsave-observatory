-- Adds the Finding Card content model to persisted findings (packet P-03).
-- Additive only: a new nullable JSONB column on analysis_findings. No DROP, no
-- ALTER of existing columns. Safe to run on existing installs — legacy rows keep
-- card = NULL and are served by the API as schema_version 0 / card:null (no
-- destructive backfill; see packages/py/contracts/findings.py for the story).
--
-- Apply with:
--   docker compose exec -T db psql -U healthsave -d healthsave \
--     < db/migrations/021_finding_cards.sql

ALTER TABLE analysis_findings
    ADD COLUMN IF NOT EXISTS card JSONB;
