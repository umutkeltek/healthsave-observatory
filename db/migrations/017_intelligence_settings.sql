-- 017_intelligence_settings.sql
--
-- Runtime, user-editable LLM-narrator ("Intelligence") settings — ADR-0003 D2.
-- Today the narrator is configured only via env / a config.yaml that is wiped on
-- redeploy. These typed tables move config into the canonical DB so a UI can edit
-- it (applies without a redeploy) and the api + worker share one source of truth.
--
-- Typed tables (NOT a generic blob), tenant-scoped via owner_id from day one:
--   * llm_credentials          — provider API keys, ENCRYPTED at rest (BYTEA
--                                Fernet ciphertext + keyring id; never returned).
--   * llm_connections          — a provider endpoint (provider/base_url/dest) +
--                                its optional credential; the unit a route points at.
--   * intelligence_settings    — one head row per owner: mode, the cloud-egress
--                                opt-in, redaction, the active revision, consent.
--   * llm_fallback_routes      — the ordered chain after the primary.
--   * intelligence_audit_events — settings/consent/credential/healthcheck trail
--                                (metadata is JSONB and MUST NOT carry secrets).
--
-- Encryption: api keys are Fernet ciphertext (same primitive as oauth_tokens,
-- migration 008); key_version names the keyring entry that sealed it so keys can
-- rotate (ADR-0003 D3). Decryption lives only in the storage boundary.
--
-- Backward-compatible by construction (additive only): no existing table touched,
-- no existing column changed, no existing index dropped. Idempotent.

BEGIN;

-- Provider credentials, encrypted at rest. One row per (owner, provider) key.
CREATE TABLE IF NOT EXISTS llm_credentials (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    provider        TEXT NOT NULL,
    api_key_enc     BYTEA NOT NULL,           -- Fernet ciphertext; never returned to a client
    key_version     TEXT NOT NULL,            -- keyring id that sealed it (rotation)
    key_last4       TEXT,                     -- non-secret display hint ("••••abcd")
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_llm_credentials_owner
    ON llm_credentials (owner_id);

-- A provider endpoint a route can point at. destination is the SERVER-validated
-- trust zone (ADR-0003 D1), not a client claim; resolved from provider + base_url.
CREATE TABLE IF NOT EXISTS llm_connections (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    provider        TEXT NOT NULL,
    display_name    TEXT,
    base_url        TEXT,
    destination     TEXT NOT NULL DEFAULT 'cloud'
        CHECK (destination IN ('local', 'cloud')),
    credential_id   BIGINT REFERENCES llm_credentials (id) ON DELETE SET NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_test_status TEXT,
    last_test_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_connections_owner
    ON llm_connections (owner_id);

-- The per-owner head row: the effective posture the resolver reads.
CREATE TABLE IF NOT EXISTS intelligence_settings (
    owner_id            UUID PRIMARY KEY DEFAULT '00000000-0000-0000-0000-000000000001',
    mode                TEXT NOT NULL DEFAULT 'off'
        CHECK (mode IN ('off', 'local', 'cloud')),
    primary_connection_id BIGINT REFERENCES llm_connections (id) ON DELETE SET NULL,
    allow_cloud_egress  BOOLEAN NOT NULL DEFAULT FALSE,   -- explicit opt-in (D4)
    redact_cloud_prompts BOOLEAN NOT NULL DEFAULT TRUE,
    revision            BIGINT NOT NULL DEFAULT 1,        -- settings_revision (D5)
    consent_version     TEXT,
    consent_text_hash   TEXT,
    consented_at        TIMESTAMPTZ,
    consented_by        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The ordered fallback chain after the primary (priority 0 = first fallback).
CREATE TABLE IF NOT EXISTS llm_fallback_routes (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    priority        INTEGER NOT NULL,
    connection_id   BIGINT NOT NULL REFERENCES llm_connections (id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    temperature     DOUBLE PRECISION,
    max_tokens      INTEGER,
    timeout_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_llm_fallback_owner_priority UNIQUE (owner_id, priority)
);

CREATE INDEX IF NOT EXISTS idx_llm_fallback_routes_owner
    ON llm_fallback_routes (owner_id, priority);

-- Audit trail for settings/consent/credential/healthcheck changes. metadata is
-- JSONB and MUST NOT carry secrets (api keys, prompt bodies, health data).
CREATE TABLE IF NOT EXISTS intelligence_audit_events (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    actor           TEXT,
    event_type      TEXT NOT NULL
        CHECK (event_type IN (
            'settings_updated', 'consent_granted', 'consent_revoked',
            'provider_healthcheck', 'credential_set', 'credential_rotated'
        )),
    before_revision BIGINT,
    after_revision  BIGINT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intelligence_audit_owner_at
    ON intelligence_audit_events (owner_id, created_at DESC);

COMMIT;
