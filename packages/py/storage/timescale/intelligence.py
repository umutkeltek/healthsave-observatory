"""TimescaleDB repository for the Intelligence (LLM-narrator) settings — ADR-0003 D2/D3.

The five owner-scoped tables from ``db/migrations/017_intelligence_settings.sql``:
``llm_credentials`` / ``llm_connections`` / ``intelligence_settings`` /
``llm_fallback_routes`` / ``intelligence_audit_events``. This repo is the only
place those tables are read or written, and the only place credential
ciphertext is sealed / unsealed (the encryption boundary, like
``oauth_tokens``). Callers see plaintext keys or key-free metadata — never
ciphertext.

Two trust rules this layer enforces by construction:

* **Secrets never round-trip to a client.** Reads that a UI/API may serialize
  (:class:`CredentialRef`, :class:`Connection`) carry only ``key_last4`` +
  ``key_version`` — never the key. The one plaintext path,
  :meth:`get_connection_secret`, is for the server-internal resolver that has
  to actually call the provider; the API layer must not serialize its result.
* **``destination`` is classified above this layer.** Whether a connection is
  ``local`` or ``cloud`` is the route-based trust decision (ADR-0003 D1), which
  lives in ``analysis.egress``. Storage sits *below* ``analysis`` in the
  one-way dependency, so it must not import it: the already-validated
  destination is passed into :meth:`upsert_connection`. The DB ``CHECK`` is the
  backstop, not the classifier.

Like the other v2 repos: a class for injection plus a ``default_repository``
and thin module-level wrappers. Every method takes the ``AsyncSession``; the
caller owns the transaction boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from auth import DEFAULT_OWNER_ID, active_key_version, last4, seal, unseal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ──────────────────────────────────────────────────────────────────────
# Frozen views — what callers get back. Credential views are key-free.
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """A stored provider credential, *without* the secret.

    Safe to surface to a UI: ``key_last4`` is a display hint and
    ``key_version`` names the keyring entry that sealed it (for rotation).
    """

    id: int
    provider: str
    key_version: str
    key_last4: str | None
    created_at: datetime
    rotated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """A provider endpoint a route can point at (``llm_connections``)."""

    id: int
    provider: str
    display_name: str | None
    base_url: str | None
    destination: str  # 'local' | 'cloud' — classified above storage (D1)
    credential_id: int | None
    enabled: bool
    last_test_status: str | None
    last_test_at: datetime | None


@dataclass(frozen=True, slots=True)
class Settings:
    """The per-owner head row — the effective posture the resolver reads."""

    owner_id: UUID
    mode: str  # 'off' | 'local' | 'cloud'
    primary_connection_id: int | None
    primary_model: str | None
    primary_temperature: float | None
    primary_max_tokens: int | None
    primary_timeout_ms: int | None
    allow_cloud_egress: bool
    redact_cloud_prompts: bool
    revision: int
    consent_version: str | None
    consent_text_hash: str | None
    consented_at: datetime | None
    consented_by: str | None


@dataclass(frozen=True, slots=True)
class FallbackRoute:
    """One row of the ordered fallback chain (``llm_fallback_routes``)."""

    id: int
    priority: int
    connection_id: int
    model: str
    temperature: float | None
    max_tokens: int | None
    timeout_ms: int | None


@dataclass(frozen=True, slots=True)
class FallbackRouteInput:
    """A fallback to write, in chain order (priority assigned by position)."""

    connection_id: int
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One row of the settings/consent/credential/healthcheck trail."""

    id: int
    actor: str | None
    event_type: str
    before_revision: int | None
    after_revision: int | None
    metadata: dict[str, Any]
    created_at: datetime


_AUDIT_EVENT_TYPES = frozenset(
    {
        "settings_updated",
        "consent_granted",
        "consent_revoked",
        "provider_healthcheck",
        "credential_set",
        "credential_rotated",
    }
)


def _parse_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


class TimescaleIntelligenceRepository:
    """TimescaleDB-backed CRUD + audit for the Intelligence settings tables.

    Stateless; every method takes the session. Encryption is applied here so
    no other layer touches ciphertext.
    """

    # ── credentials ─────────────────────────────────────────────────

    async def put_credential(
        self,
        session: AsyncSession,
        *,
        provider: str,
        api_key: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> CredentialRef:
        """Seal ``api_key`` with the keyring head and insert a new credential row.

        Records a ``credential_set`` audit event. Returns the key-free ref.
        """
        sealed = seal(api_key)
        hint = last4(api_key)
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO llm_credentials
                        (owner_id, provider, api_key_enc, key_version, key_last4)
                    VALUES (:owner_id, :provider, :api_key_enc, :key_version, :key_last4)
                    RETURNING id, created_at
                    """
                ),
                {
                    "owner_id": str(owner_id),
                    "provider": provider,
                    "api_key_enc": sealed.ciphertext,
                    "key_version": sealed.key_version,
                    "key_last4": hint,
                },
            )
        ).first()
        await self.record_audit(
            session,
            owner_id=owner_id,
            event_type="credential_set",
            metadata={"provider": provider, "credential_id": row.id},
        )
        return CredentialRef(
            id=row.id,
            provider=provider,
            key_version=sealed.key_version,
            key_last4=hint,
            created_at=row.created_at,
        )

    async def rotate_credential(
        self,
        session: AsyncSession,
        *,
        credential_id: int,
        api_key: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> None:
        """Re-seal an existing credential with the current head key.

        Used both to change the key value and to migrate a row onto a rotated
        head (``key_version`` advances to :func:`auth.active_key_version`).
        Records a ``credential_rotated`` audit event.
        """
        sealed = seal(api_key)
        await session.execute(
            text(
                """
                UPDATE llm_credentials
                   SET api_key_enc = :api_key_enc,
                       key_version = :key_version,
                       key_last4   = :key_last4,
                       rotated_at  = NOW()
                 WHERE id = :id AND owner_id = :owner_id
                """
            ),
            {
                "id": credential_id,
                "owner_id": str(owner_id),
                "api_key_enc": sealed.ciphertext,
                "key_version": sealed.key_version,
                "key_last4": last4(api_key),
            },
        )
        await self.record_audit(
            session,
            owner_id=owner_id,
            event_type="credential_rotated",
            metadata={"credential_id": credential_id, "key_version": sealed.key_version},
        )

    async def get_credential(
        self,
        session: AsyncSession,
        *,
        credential_id: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> CredentialRef | None:
        """Key-free credential metadata, or None."""
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, provider, key_version, key_last4, created_at, rotated_at
                      FROM llm_credentials
                     WHERE id = :id AND owner_id = :owner_id
                    """
                ),
                {"id": credential_id, "owner_id": str(owner_id)},
            )
        ).first()
        if row is None:
            return None
        return CredentialRef(
            id=row.id,
            provider=row.provider,
            key_version=row.key_version,
            key_last4=row.key_last4,
            created_at=row.created_at,
            rotated_at=row.rotated_at,
        )

    async def get_connection_secret(
        self,
        session: AsyncSession,
        *,
        connection_id: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> str | None:
        """Decrypt the API key backing ``connection_id`` — server-internal only.

        Returns the plaintext key for the resolver that must call the provider,
        or None when the connection has no credential. The API layer must NOT
        serialize this. Raises :class:`auth.TokenEncryptionError` if no ring key
        opens the ciphertext (e.g. a retired key was dropped too early).
        """
        row = (
            await session.execute(
                text(
                    """
                    SELECT c.api_key_enc, c.key_version
                      FROM llm_connections AS conn
                      JOIN llm_credentials AS c ON c.id = conn.credential_id
                     WHERE conn.id = :id AND conn.owner_id = :owner_id
                    """
                ),
                {"id": connection_id, "owner_id": str(owner_id)},
            )
        ).first()
        if row is None or row.api_key_enc is None:
            return None
        return unseal(bytes(row.api_key_enc), key_version=row.key_version)

    # ── connections ─────────────────────────────────────────────────

    async def upsert_connection(
        self,
        session: AsyncSession,
        *,
        provider: str,
        destination: str,
        connection_id: int | None = None,
        display_name: str | None = None,
        base_url: str | None = None,
        credential_id: int | None = None,
        enabled: bool = True,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Connection:
        """Insert (``connection_id is None``) or update a connection.

        ``destination`` MUST already be the route-classified value
        (``'local'`` | ``'cloud'``) from ``analysis.egress`` — storage does not
        classify (D1). The DB CHECK rejects anything else.
        """
        if destination not in ("local", "cloud"):
            raise ValueError(f"destination must be 'local'|'cloud', got {destination!r}")
        params = {
            "owner_id": str(owner_id),
            "provider": provider,
            "display_name": display_name,
            "base_url": base_url,
            "destination": destination,
            "credential_id": credential_id,
            "enabled": enabled,
        }
        if connection_id is None:
            sql = text(
                """
                INSERT INTO llm_connections
                    (owner_id, provider, display_name, base_url, destination,
                     credential_id, enabled)
                VALUES (:owner_id, :provider, :display_name, :base_url, :destination,
                        :credential_id, :enabled)
                RETURNING id, provider, display_name, base_url, destination,
                          credential_id, enabled, last_test_status, last_test_at
                """
            )
        else:
            params["id"] = connection_id
            sql = text(
                """
                UPDATE llm_connections
                   SET provider = :provider, display_name = :display_name,
                       base_url = :base_url, destination = :destination,
                       credential_id = :credential_id, enabled = :enabled,
                       updated_at = NOW()
                 WHERE id = :id AND owner_id = :owner_id
                RETURNING id, provider, display_name, base_url, destination,
                          credential_id, enabled, last_test_status, last_test_at
                """
            )
        row = (await session.execute(sql, params)).first()
        return _connection_from_row(row)

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Connection | None:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, provider, display_name, base_url, destination,
                           credential_id, enabled, last_test_status, last_test_at
                      FROM llm_connections
                     WHERE id = :id AND owner_id = :owner_id
                    """
                ),
                {"id": connection_id, "owner_id": str(owner_id)},
            )
        ).first()
        return _connection_from_row(row) if row is not None else None

    async def list_connections(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> list[Connection]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, provider, display_name, base_url, destination,
                           credential_id, enabled, last_test_status, last_test_at
                      FROM llm_connections
                     WHERE owner_id = :owner_id
                     ORDER BY id
                    """
                ),
                {"owner_id": str(owner_id)},
            )
        ).fetchall()
        return [_connection_from_row(row) for row in rows]

    async def record_test_result(
        self,
        session: AsyncSession,
        *,
        connection_id: int,
        status: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> None:
        """Stamp a connection's last health-check result + audit it."""
        await session.execute(
            text(
                """
                UPDATE llm_connections
                   SET last_test_status = :status, last_test_at = NOW(), updated_at = NOW()
                 WHERE id = :id AND owner_id = :owner_id
                """
            ),
            {"id": connection_id, "owner_id": str(owner_id), "status": status},
        )
        await self.record_audit(
            session,
            owner_id=owner_id,
            event_type="provider_healthcheck",
            metadata={"connection_id": connection_id, "status": status},
        )

    # ── settings (head row) ─────────────────────────────────────────

    async def get_settings(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Settings | None:
        """The head settings row, or None when the owner has never configured."""
        row = (
            await session.execute(
                text(
                    """
                    SELECT owner_id, mode, primary_connection_id, primary_model,
                           primary_temperature, primary_max_tokens, primary_timeout_ms,
                           allow_cloud_egress, redact_cloud_prompts, revision,
                           consent_version, consent_text_hash, consented_at, consented_by
                      FROM intelligence_settings
                     WHERE owner_id = :owner_id
                    """
                ),
                {"owner_id": str(owner_id)},
            )
        ).first()
        if row is None:
            return None
        return Settings(
            owner_id=UUID(str(row.owner_id)),
            mode=row.mode,
            primary_connection_id=row.primary_connection_id,
            primary_model=row.primary_model,
            primary_temperature=row.primary_temperature,
            primary_max_tokens=row.primary_max_tokens,
            primary_timeout_ms=row.primary_timeout_ms,
            allow_cloud_egress=row.allow_cloud_egress,
            redact_cloud_prompts=row.redact_cloud_prompts,
            revision=row.revision,
            consent_version=row.consent_version,
            consent_text_hash=row.consent_text_hash,
            consented_at=row.consented_at,
            consented_by=row.consented_by,
        )

    async def update_settings(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        actor: str | None = None,
        **fields: Any,
    ) -> Settings:
        """Upsert the head row, bump ``revision`` atomically, and audit it.

        Accepts any subset of the posture columns (``mode``,
        ``primary_connection_id``, ``primary_model``, ``primary_temperature``,
        ``primary_max_tokens``, ``primary_timeout_ms``, ``allow_cloud_egress``,
        ``redact_cloud_prompts``). Consent columns are written via
        :meth:`record_consent`, not here. The revision bump is done in-SQL
        (``revision + 1`` on conflict) so concurrent writers can't reuse a
        number; the xmax trick tells insert from update for the audit's
        ``before_revision``.
        """
        allowed = {
            "mode",
            "primary_connection_id",
            "primary_model",
            "primary_temperature",
            "primary_max_tokens",
            "primary_timeout_ms",
            "allow_cloud_egress",
            "redact_cloud_prompts",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"update_settings got unknown field(s): {sorted(unknown)}")

        # Insert defaults for a first write; on conflict, patch only the named
        # columns via COALESCE(:field, existing) and bump revision.
        params: dict[str, Any] = {"owner_id": str(owner_id)}
        for col in allowed:
            params[col] = fields.get(col)
        # mode has a NOT NULL default; a first INSERT with NULL would fail, so
        # fall back to 'off' for the insert path only.
        insert_mode = params["mode"] if params["mode"] is not None else "off"
        params["insert_mode"] = insert_mode
        params["insert_allow_cloud"] = bool(params["allow_cloud_egress"])
        params["insert_redact"] = (
            True if params["redact_cloud_prompts"] is None else bool(params["redact_cloud_prompts"])
        )

        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO intelligence_settings
                        (owner_id, mode, primary_connection_id, primary_model,
                         primary_temperature, primary_max_tokens, primary_timeout_ms,
                         allow_cloud_egress, redact_cloud_prompts, revision)
                    VALUES
                        (:owner_id, :insert_mode, :primary_connection_id, :primary_model,
                         :primary_temperature, :primary_max_tokens, :primary_timeout_ms,
                         :insert_allow_cloud, :insert_redact, 1)
                    ON CONFLICT (owner_id) DO UPDATE SET
                         mode = COALESCE(:mode, intelligence_settings.mode),
                         primary_connection_id =
                             COALESCE(:primary_connection_id,
                                      intelligence_settings.primary_connection_id),
                         primary_model = COALESCE(:primary_model,
                                                  intelligence_settings.primary_model),
                         primary_temperature = COALESCE(:primary_temperature,
                                                  intelligence_settings.primary_temperature),
                         primary_max_tokens = COALESCE(:primary_max_tokens,
                                                  intelligence_settings.primary_max_tokens),
                         primary_timeout_ms = COALESCE(:primary_timeout_ms,
                                                  intelligence_settings.primary_timeout_ms),
                         allow_cloud_egress = COALESCE(:allow_cloud_egress,
                                                  intelligence_settings.allow_cloud_egress),
                         redact_cloud_prompts = COALESCE(:redact_cloud_prompts,
                                                  intelligence_settings.redact_cloud_prompts),
                         revision = intelligence_settings.revision + 1,
                         updated_at = NOW()
                    RETURNING revision, (xmax <> 0) AS was_update
                    """
                ),
                params,
            )
        ).first()
        after = row.revision
        before = (after - 1) if row.was_update else None
        await self.record_audit(
            session,
            owner_id=owner_id,
            actor=actor,
            event_type="settings_updated",
            before_revision=before,
            after_revision=after,
            metadata={"changed": sorted(k for k, v in fields.items() if v is not None)},
        )
        settings = await self.get_settings(session, owner_id=owner_id)
        assert settings is not None  # just upserted
        return settings

    async def record_consent(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        granted: bool,
        consent_version: str | None = None,
        consent_text_hash: str | None = None,
        consented_by: str | None = None,
        actor: str | None = None,
    ) -> None:
        """Record (or revoke) cloud-egress consent on the head row + audit it.

        Granting stamps the four ``consent_*`` columns; revoking clears them.
        The row must already exist (created by :meth:`update_settings`); consent
        is a decision *about* an existing posture, so we update, never insert.
        """
        if granted:
            await session.execute(
                text(
                    """
                    UPDATE intelligence_settings
                       SET consent_version = :version, consent_text_hash = :hash,
                           consented_at = NOW(), consented_by = :by, updated_at = NOW()
                     WHERE owner_id = :owner_id
                    """
                ),
                {
                    "owner_id": str(owner_id),
                    "version": consent_version,
                    "hash": consent_text_hash,
                    "by": consented_by,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE intelligence_settings
                       SET consent_version = NULL, consent_text_hash = NULL,
                           consented_at = NULL, consented_by = NULL, updated_at = NOW()
                     WHERE owner_id = :owner_id
                    """
                ),
                {"owner_id": str(owner_id)},
            )
        await self.record_audit(
            session,
            owner_id=owner_id,
            actor=actor,
            event_type="consent_granted" if granted else "consent_revoked",
            metadata={"consent_version": consent_version} if granted else {},
        )

    # ── fallback chain ──────────────────────────────────────────────

    async def get_fallback_routes(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> list[FallbackRoute]:
        """The fallback chain, ordered by priority (0 = first fallback)."""
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, priority, connection_id, model,
                           temperature, max_tokens, timeout_ms
                      FROM llm_fallback_routes
                     WHERE owner_id = :owner_id
                     ORDER BY priority
                    """
                ),
                {"owner_id": str(owner_id)},
            )
        ).fetchall()
        return [
            FallbackRoute(
                id=row.id,
                priority=row.priority,
                connection_id=row.connection_id,
                model=row.model,
                temperature=row.temperature,
                max_tokens=row.max_tokens,
                timeout_ms=row.timeout_ms,
            )
            for row in rows
        ]

    async def set_fallback_routes(
        self,
        session: AsyncSession,
        *,
        routes: list[FallbackRouteInput],
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> None:
        """Replace the whole fallback chain; priority is assigned by list order.

        Delete-then-insert keeps the ``UNIQUE(owner_id, priority)`` constraint
        trivially satisfied and makes reordering a single call. The caller's
        transaction makes it atomic.
        """
        await session.execute(
            text("DELETE FROM llm_fallback_routes WHERE owner_id = :owner_id"),
            {"owner_id": str(owner_id)},
        )
        for priority, route in enumerate(routes):
            await session.execute(
                text(
                    """
                    INSERT INTO llm_fallback_routes
                        (owner_id, priority, connection_id, model,
                         temperature, max_tokens, timeout_ms)
                    VALUES (:owner_id, :priority, :connection_id, :model,
                            :temperature, :max_tokens, :timeout_ms)
                    """
                ),
                {
                    "owner_id": str(owner_id),
                    "priority": priority,
                    "connection_id": route.connection_id,
                    "model": route.model,
                    "temperature": route.temperature,
                    "max_tokens": route.max_tokens,
                    "timeout_ms": route.timeout_ms,
                },
            )

    # ── audit ───────────────────────────────────────────────────────

    async def record_audit(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        event_type: str,
        actor: str | None = None,
        before_revision: int | None = None,
        after_revision: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append an audit event. ``metadata`` MUST NOT carry secrets.

        Callers pass non-sensitive context only (provider name, connection id,
        status) — never an API key, a prompt body, or any health data.
        """
        if event_type not in _AUDIT_EVENT_TYPES:
            raise ValueError(f"unknown audit event_type {event_type!r}")
        await session.execute(
            text(
                """
                INSERT INTO intelligence_audit_events
                    (owner_id, actor, event_type, before_revision, after_revision, metadata)
                VALUES (:owner_id, :actor, :event_type, :before_revision, :after_revision,
                        CAST(:metadata AS JSONB))
                """
            ),
            {
                "owner_id": str(owner_id),
                "actor": actor,
                "event_type": event_type,
                "before_revision": before_revision,
                "after_revision": after_revision,
                "metadata": json.dumps(metadata or {}),
            },
        )

    async def list_audit_events(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Recent audit events, newest first."""
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, actor, event_type, before_revision, after_revision,
                           metadata, created_at
                      FROM intelligence_audit_events
                     WHERE owner_id = :owner_id
                     ORDER BY created_at DESC
                     LIMIT :limit
                    """
                ),
                {"owner_id": str(owner_id), "limit": limit},
            )
        ).fetchall()
        return [
            AuditEvent(
                id=row.id,
                actor=row.actor,
                event_type=row.event_type,
                before_revision=row.before_revision,
                after_revision=row.after_revision,
                metadata=_parse_metadata(row.metadata),
                created_at=row.created_at,
            )
            for row in rows
        ]


def _connection_from_row(row: Any) -> Connection:
    return Connection(
        id=row.id,
        provider=row.provider,
        display_name=row.display_name,
        base_url=row.base_url,
        destination=row.destination,
        credential_id=row.credential_id,
        enabled=row.enabled,
        last_test_status=getattr(row, "last_test_status", None),
        last_test_at=getattr(row, "last_test_at", None),
    )


# Default instance for callers that haven't migrated to injection.
default_repository = TimescaleIntelligenceRepository()


# ── module-level convenience wrappers (delegate to default_repository) ──

# Re-export the active keyring version so callers (e.g. a rotation runbook or
# the API's "needs re-seal?" check) don't import auth directly.
active_credential_key_version = active_key_version


async def get_settings(
    session: AsyncSession, *, owner_id: UUID = DEFAULT_OWNER_ID
) -> Settings | None:
    return await default_repository.get_settings(session, owner_id=owner_id)


async def get_connection(
    session: AsyncSession, *, connection_id: int, owner_id: UUID = DEFAULT_OWNER_ID
) -> Connection | None:
    return await default_repository.get_connection(
        session, connection_id=connection_id, owner_id=owner_id
    )


async def list_connections(
    session: AsyncSession, *, owner_id: UUID = DEFAULT_OWNER_ID
) -> list[Connection]:
    return await default_repository.list_connections(session, owner_id=owner_id)


async def get_fallback_routes(
    session: AsyncSession, *, owner_id: UUID = DEFAULT_OWNER_ID
) -> list[FallbackRoute]:
    return await default_repository.get_fallback_routes(session, owner_id=owner_id)


async def get_connection_secret(
    session: AsyncSession, *, connection_id: int, owner_id: UUID = DEFAULT_OWNER_ID
) -> str | None:
    return await default_repository.get_connection_secret(
        session, connection_id=connection_id, owner_id=owner_id
    )
