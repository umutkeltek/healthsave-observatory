-- 008_oauth_tokens.sql
--
-- OAuth token storage for poll-based source plugins (Whoop today,
-- Amazfit/Zepp + future providers next). Per-owner, per-provider
-- unique. Refresh handlers update the row in place so the latest
-- access + refresh pair always lives at one row per (owner, provider).
--
-- Encryption at rest:
--   * access_token_enc / refresh_token_enc are BYTEA Fernet ciphertexts.
--   * Key lives in env HDH_TOKEN_ENC_KEY (URL-safe base64, 32 bytes).
--   * cryptography.fernet.Fernet handles auth + IV; rows are tamper-
--     evident by construction.
--
-- Audit:
--   * oauth_token_events captures the lifecycle (authorized, refreshed,
--     revoked, refresh_failed) so operators can detect token decay
--     without grepping logs.
--
-- Backward-compatible by construction (additive only):
--   * No existing table touched.
--   * No existing column changed.
--   * No existing index dropped.

BEGIN;

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id                  BIGSERIAL PRIMARY KEY,
    owner_id            UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    provider            TEXT NOT NULL,
    access_token_enc    BYTEA NOT NULL,
    refresh_token_enc   BYTEA,
    expires_at          TIMESTAMPTZ,
    scopes              TEXT[] NOT NULL DEFAULT '{}',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_oauth_tokens_owner_provider UNIQUE (owner_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_oauth_tokens_provider
    ON oauth_tokens (provider);

CREATE INDEX IF NOT EXISTS idx_oauth_tokens_expires_at
    ON oauth_tokens (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS oauth_token_events (
    id                  BIGSERIAL PRIMARY KEY,
    owner_id            UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    provider            TEXT NOT NULL,
    event_kind          TEXT NOT NULL
        CHECK (event_kind IN ('authorized', 'refreshed', 'revoked', 'refresh_failed')),
    event_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_oauth_token_events_provider_at
    ON oauth_token_events (provider, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_oauth_token_events_owner_at
    ON oauth_token_events (owner_id, event_at DESC);

COMMIT;
