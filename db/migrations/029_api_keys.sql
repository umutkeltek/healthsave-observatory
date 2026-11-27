-- 029_api_keys.sql
--
-- Participant API keys: one Observatory per coach or clinic, one key per
-- participant. A participant is an owner; the key a phone holds decides
-- which owner_id its rows are written under. The shipped iOS and Android
-- apps change nothing: same routes, same X-API-Key header.
--
-- * The legacy single API_KEY from .env is NOT stored here. It keeps working
--   unchanged and maps to the default owner with admin scope.
-- * key_hash is the lowercase hex SHA-256 of the exact key bytes. The
--   plaintext key is printed once by `healthsave participants add` and never
--   stored anywhere.
-- * Every key that shares a label shares one owner_id (revoke + add re-pairs a
--   lost phone without splitting the person's history). Revoked keys stay as
--   rows: revocation is a timestamp, and the data stays readable to the admin.
--
-- Additive only: a new table and its indexes; no existing object touched.
-- Every unique index on the metric tables already includes owner_id
-- (migrations 003, 012, 024, 025).

BEGIN;

CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash    TEXT NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    label       TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 64),
    scope       TEXT NOT NULL CHECK (scope IN ('ingest', 'read', 'admin')),
    owner_id    UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_key_hash
    ON api_keys (key_hash);

-- One live key per label and scope; revoked rows are history.
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_live_label_scope
    ON api_keys (lower(label), scope)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_api_keys_owner
    ON api_keys (owner_id);

COMMIT;
