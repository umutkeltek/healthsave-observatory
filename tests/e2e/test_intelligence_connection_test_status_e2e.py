"""E2E: a connection's test result does not outlive the key or endpoint it tested.

``POST /api/v2/intelligence/test-connection`` stamps ``last_test_status`` on
the connection. A later save that changed the provider, the base URL or the
key kept the old "ok", so the settings page showed a tested connection that
had never been tested.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.fixture
def keyring(monkeypatch):
    from auth import generate_key
    from auth.keyring import _keyring_from_env

    monkeypatch.delenv("HDH_KEYRING", raising=False)
    monkeypatch.setenv("HDH_TOKEN_ENC_KEY", generate_key())
    _keyring_from_env.cache_clear()
    yield
    _keyring_from_env.cache_clear()


@pytest.mark.asyncio
async def test_a_changed_endpoint_or_key_clears_the_test_result(keyring) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.intelligence import default_repository as repo

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    try:
        async with AsyncSession(engine) as session:
            cred = await repo.put_credential(
                session, provider="openai", api_key="sk-first", owner_id=owner
            )

            async def save(base_url: str) -> int:
                conn = await repo.upsert_connection(
                    session,
                    connection_id=conn_id,
                    provider="openai",
                    destination="cloud",
                    base_url=base_url,
                    credential_id=cred.id,
                    owner_id=owner,
                )
                return conn.id

            async def tested_ok() -> None:
                await repo.record_test_result(
                    session, connection_id=conn_id, status="ok", owner_id=owner
                )

            conn_id = None
            conn_id = await save("https://api.openai.com/v1")
            await tested_ok()

            # Same endpoint and key: the result still describes this connection.
            await save("https://api.openai.com/v1")
            same = await repo.get_connection(session, connection_id=conn_id, owner_id=owner)
            assert same.last_test_status == "ok"

            # A different endpoint was never tested.
            await save("https://proxy.example.com/v1")
            moved = await repo.get_connection(session, connection_id=conn_id, owner_id=owner)
            assert moved.last_test_status is None
            assert moved.last_test_at is None

            # A new key was never tested either.
            await tested_ok()
            await repo.rotate_credential(
                session, credential_id=cred.id, api_key="sk-second", owner_id=owner
            )
            rekeyed = await repo.get_connection(session, connection_id=conn_id, owner_id=owner)
            assert rekeyed.last_test_status is None
            await session.rollback()
    finally:
        await engine.dispose()
