"""TimescaleDB repository for the ``oauth_tokens`` + ``oauth_token_events`` tables.

Pure CRUD + audit. Encryption is handled at this boundary — callers
see plaintext :class:`auth.OAuthToken` instances, never ciphertext.

The four ``event_kind`` values match the CHECK constraint in
``db/migrations/008_oauth_tokens.sql``:

  * ``authorized``      — first store after the user grants.
  * ``refreshed``       — after a successful refresh.
  * ``revoked``         — row deleted on user-initiated unlink.
  * ``refresh_failed``  — refresh endpoint returned an error; token
    row left intact (the caller decides whether to revoke or retry).
"""

from __future__ import annotations

import json
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken, decrypt, encrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_token(
    session: AsyncSession,
    *,
    provider: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken | None:
    """Return the current token for ``(owner_id, provider)`` or None if absent."""
    row = (
        await session.execute(
            text(
                """
                SELECT access_token_enc, refresh_token_enc, expires_at,
                       scopes, metadata
                  FROM oauth_tokens
                 WHERE owner_id = :owner_id AND provider = :provider
                """
            ),
            {"owner_id": str(owner_id), "provider": provider},
        )
    ).first()
    if row is None:
        return None
    return OAuthToken(
        owner_id=owner_id,
        provider=provider,
        access_token=decrypt(bytes(row.access_token_enc)),
        refresh_token=(decrypt(bytes(row.refresh_token_enc)) if row.refresh_token_enc else None),
        expires_at=row.expires_at,
        scopes=tuple(row.scopes or ()),
        metadata=dict(row.metadata or {}),
    )


async def put_token(
    session: AsyncSession,
    token: OAuthToken,
    *,
    event_kind: str = "authorized",
) -> None:
    """Upsert the token row, encrypt secrets, append an audit event.

    ``event_kind`` MUST be one of ``authorized`` / ``refreshed`` /
    ``revoked``; ``refresh_failed`` is recorded via
    :func:`record_refresh_failure` because it has an error message.
    """
    if event_kind not in {"authorized", "refreshed", "revoked"}:
        raise ValueError(
            f"put_token event_kind must be authorized|refreshed|revoked, got {event_kind!r}"
        )
    await session.execute(
        text(
            """
            INSERT INTO oauth_tokens
                (owner_id, provider, access_token_enc, refresh_token_enc,
                 expires_at, scopes, metadata, updated_at)
            VALUES (:owner_id, :provider, :access_enc, :refresh_enc,
                    :expires_at, :scopes, CAST(:metadata AS JSONB), NOW())
            ON CONFLICT (owner_id, provider) DO UPDATE
              SET access_token_enc  = EXCLUDED.access_token_enc,
                  refresh_token_enc = EXCLUDED.refresh_token_enc,
                  expires_at        = EXCLUDED.expires_at,
                  scopes            = EXCLUDED.scopes,
                  metadata          = EXCLUDED.metadata,
                  updated_at        = NOW()
            """
        ),
        {
            "owner_id": str(token.owner_id),
            "provider": token.provider,
            "access_enc": encrypt(token.access_token),
            "refresh_enc": (encrypt(token.refresh_token) if token.refresh_token else None),
            "expires_at": token.expires_at,
            "scopes": list(token.scopes),
            "metadata": json.dumps(token.metadata),
        },
    )
    await _record_event(session, token.owner_id, token.provider, event_kind)


async def revoke_token(
    session: AsyncSession,
    *,
    provider: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> None:
    """Delete the token row and append a ``revoked`` audit event."""
    await session.execute(
        text("DELETE FROM oauth_tokens WHERE owner_id = :owner_id AND provider = :provider"),
        {"owner_id": str(owner_id), "provider": provider},
    )
    await _record_event(session, owner_id, provider, "revoked")


async def record_refresh_failure(
    session: AsyncSession,
    *,
    provider: str,
    error_message: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> None:
    """Append a ``refresh_failed`` event so operators can detect token decay."""
    await session.execute(
        text(
            """
            INSERT INTO oauth_token_events (owner_id, provider, event_kind, error_message)
            VALUES (:owner_id, :provider, 'refresh_failed', :error_message)
            """
        ),
        {
            "owner_id": str(owner_id),
            "provider": provider,
            "error_message": error_message,
        },
    )


async def _record_event(
    session: AsyncSession,
    owner_id: UUID,
    provider: str,
    event_kind: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO oauth_token_events (owner_id, provider, event_kind)
            VALUES (:owner_id, :provider, :event_kind)
            """
        ),
        {
            "owner_id": str(owner_id),
            "provider": provider,
            "event_kind": event_kind,
        },
    )
