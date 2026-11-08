"""E2E: the source-poll cursor on real PostgreSQL (migration 031)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.mark.asyncio
async def test_the_cursor_records_per_owner_and_provider_and_never_moves_back() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.source_poll_cursors import (
        get_last_successful_poll,
        record_successful_poll,
    )

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner, other_owner = uuid4(), uuid4()
    newer = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    try:
        async with AsyncSession(engine) as session:
            assert await get_last_successful_poll(session, provider="whoop", owner_id=owner) is None

            await record_successful_poll(session, provider="whoop", owner_id=owner, polled_at=newer)
            # A slow poll that started earlier but finished later must not
            # move the cursor back.
            await record_successful_poll(
                session, provider="whoop", owner_id=owner, polled_at=newer - timedelta(hours=1)
            )

            assert (
                await get_last_successful_poll(session, provider="whoop", owner_id=owner) == newer
            )
            assert await get_last_successful_poll(session, provider="polar", owner_id=owner) is None
            assert (
                await get_last_successful_poll(session, provider="whoop", owner_id=other_owner)
                is None
            )
            await session.rollback()
    finally:
        await engine.dispose()
