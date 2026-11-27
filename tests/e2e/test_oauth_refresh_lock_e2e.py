"""E2E: two refreshes of one expired token spend its refresh token once.

The worker poll and the Whoop webhook can find the same expired token at the
same time. Both sent the stored refresh token; Whoop rotates it on the first
use, so the second refresh failed (and providers may revoke a reused refresh
token's whole grant). The refresh now takes a row lock and re-reads the token,
so the second caller uses the token the first one stored.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _Whoop:
    """Token endpoint that takes a moment and rotates the refresh token."""

    def __init__(self) -> None:
        self.refreshes: list[str] = []

    async def post(self, url, *, data=None, headers=None):
        self.refreshes.append(data["refresh_token"])
        await asyncio.sleep(0.3)
        n = len(self.refreshes)
        return _Response(
            {
                "access_token": f"AT-{n}",
                "refresh_token": f"RT-{n}",
                "expires_in": 3600,
                "scope": "offline",
                "token_type": "Bearer",
            }
        )


@pytest.mark.asyncio
async def test_concurrent_refreshes_spend_the_refresh_token_once(monkeypatch) -> None:
    from auth import DEFAULT_OWNER_ID, OAuthToken, generate_key
    from auth.encryption import _fernet_from_env
    from plugin_sdk import find_plugin_manifest, load_manifest
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale import oauth_tokens

    from plugins.sources.whoop import WhoopSource
    from plugins.sources.whoop.oauth import WhoopClientConfig

    monkeypatch.setenv("HDH_TOKEN_ENC_KEY", generate_key())
    _fernet_from_env.cache_clear()
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    assert owner != DEFAULT_OWNER_ID
    whoop = _Whoop()
    plugin = WhoopSource(load_manifest(find_plugin_manifest("whoop", kind="source")))
    config = WhoopClientConfig(client_id="c", client_secret="s", redirect_uri="https://t/cb")
    try:
        async with AsyncSession(engine) as session:
            await oauth_tokens.put_token(
                session,
                OAuthToken(
                    owner_id=owner,
                    provider="whoop",
                    access_token="AT-0",
                    refresh_token="RT-0",
                    expires_at=datetime.now(UTC) - timedelta(minutes=5),
                ),
            )
            await session.commit()

        async def load():
            async with AsyncSession(engine) as session:
                token = await plugin._load_valid_token(
                    {},
                    session=session,
                    http_client=whoop,
                    owner_id=owner,
                    token_store=oauth_tokens,
                    oauth_config=config,
                )
                await session.commit()
                return token

        first, second = await asyncio.gather(load(), load())

        assert whoop.refreshes == ["RT-0"]
        assert first.access_token == second.access_token == "AT-1"
    finally:
        async with AsyncSession(engine) as session:
            for table in ("oauth_tokens", "oauth_token_events"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE owner_id = :owner"), {"owner": owner}
                )
            await session.commit()
        await engine.dispose()
        _fernet_from_env.cache_clear()


@pytest.mark.asyncio
async def test_a_refresh_keeps_the_metadata_authorizing_stored(monkeypatch) -> None:
    """A refresh response has no account details; it must not erase them."""
    from auth import OAuthToken, generate_key
    from auth.encryption import _fernet_from_env
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale import oauth_tokens

    monkeypatch.setenv("HDH_TOKEN_ENC_KEY", generate_key())
    _fernet_from_env.cache_clear()
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = uuid4()

    def token(access: str, metadata: dict) -> OAuthToken:
        return OAuthToken(
            owner_id=owner,
            provider="whoop",
            access_token=access,
            refresh_token="RT",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            metadata=metadata,
        )

    try:
        async with factory() as session:
            await oauth_tokens.put_token(
                session, token("AT-1", {"provider_subject_id": "whoop-user-7", "token_type": "x"})
            )
            await oauth_tokens.put_token(
                session, token("AT-2", {"token_type": "Bearer"}), event_kind="refreshed"
            )
            await session.commit()
            stored = await oauth_tokens.get_token(session, provider="whoop", owner_id=owner)
        assert stored.access_token == "AT-2"
        assert stored.metadata == {"provider_subject_id": "whoop-user-7", "token_type": "Bearer"}

        async with factory() as session:  # authorizing again replaces it
            await oauth_tokens.put_token(session, token("AT-3", {"token_type": "Bearer"}))
            await session.commit()
            stored = await oauth_tokens.get_token(session, provider="whoop", owner_id=owner)
        assert stored.metadata == {"token_type": "Bearer"}
    finally:
        from sqlalchemy import text

        async with factory() as session:
            for table in ("oauth_tokens", "oauth_token_events"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE owner_id = :owner"), {"owner": owner}
                )
            await session.commit()
        await engine.dispose()
        _fernet_from_env.cache_clear()
