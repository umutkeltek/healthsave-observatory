"""E2E: the replay owner check reads keys and receipts on real PostgreSQL."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.mark.asyncio
async def test_owners_with_a_receipt_or_a_key_are_seen() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.ingest import ingest_owner_ids

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    with_receipt, with_key = uuid4(), uuid4()
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                text(
                    "INSERT INTO healthsave_sync_receipts (owner_id, metric, status) "
                    "VALUES (:owner, 'heart_rate', 'processed')"
                ),
                {"owner": with_receipt},
            )
            await session.execute(
                text(
                    "INSERT INTO api_keys (key_hash, label, scope, owner_id) "
                    "VALUES (:hash, :label, 'ingest', :owner)"
                ),
                {"hash": uuid4().hex * 2, "label": f"e2e {with_key}"[:64], "owner": with_key},
            )

            owners = await ingest_owner_ids(session)

            assert {with_receipt, with_key} <= owners
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_database_without_api_keys_does_not_crash_the_owner_check() -> None:
    """Before migration 029 there is no api_keys table; receipts still count."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.ingest import ingest_owner_ids

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    schema = f"e2e_pre029_{uuid4().hex[:12]}"
    owner = uuid4()
    try:
        async with AsyncSession(engine) as session:
            # A throwaway schema with receipts but no api_keys, rolled back below.
            await session.execute(text(f"CREATE SCHEMA {schema}"))
            await session.execute(
                text(f"CREATE TABLE {schema}.healthsave_sync_receipts (owner_id UUID)")
            )
            await session.execute(
                text(f"INSERT INTO {schema}.healthsave_sync_receipts VALUES (:owner)"),
                {"owner": owner},
            )
            await session.execute(text(f"SET LOCAL search_path TO {schema}"))

            assert await ingest_owner_ids(session) == {owner}
            await session.rollback()
    finally:
        await engine.dispose()
