-- 030_intelligence_audit_narrator_failover.sql
--
-- Allow the 'narrator_failover' audit event.
--
-- The repository allowlist (storage/timescale/intelligence.py) gained
-- 'narrator_failover' for briefs served by a fallback narrator, but the CHECK
-- from 017 never did. Every failover audit insert failed the CHECK, which
-- aborted the briefing's transaction on PostgreSQL, so the briefing failed
-- with a deterministic error after the narrator had already answered.
--
-- Widening a CHECK means dropping it and adding the wider one. In effect this
-- is additive: every value 017 allowed is still allowed, no row changes, and
-- no table or column is renamed or dropped.
BEGIN;

ALTER TABLE intelligence_audit_events
    DROP CONSTRAINT IF EXISTS intelligence_audit_events_event_type_check;

ALTER TABLE intelligence_audit_events
    ADD CONSTRAINT intelligence_audit_events_event_type_check
    CHECK (event_type IN (
        'settings_updated', 'consent_granted', 'consent_revoked',
        'provider_healthcheck', 'credential_set', 'credential_rotated',
        'narrator_failover'
    ));

COMMIT;
