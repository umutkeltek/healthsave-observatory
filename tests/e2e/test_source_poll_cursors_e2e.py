"""E2E: the source-poll cursor on real PostgreSQL (migrations 031 and 032)."""

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


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


@pytest.mark.asyncio
async def test_the_cursor_records_per_owner_and_provider_and_never_moves_back() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.source_poll_cursors import get_poll_cursor, record_successful_poll

    engine = _engine()
    owner, other_owner = uuid4(), uuid4()
    newer = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    try:
        async with AsyncSession(engine) as session:
            assert await get_poll_cursor(session, provider="whoop", owner_id=owner) is None

            await record_successful_poll(session, provider="whoop", owner_id=owner, polled_at=newer)
            # A slow poll that started earlier but finished later must not
            # move the cursor back.
            await record_successful_poll(
                session, provider="whoop", owner_id=owner, polled_at=newer - timedelta(hours=1)
            )

            cursor = await get_poll_cursor(session, provider="whoop", owner_id=owner)
            assert cursor.last_success_at == newer
            assert cursor.backfill_failures == 0
            assert await get_poll_cursor(session, provider="polar", owner_id=owner) is None
            assert await get_poll_cursor(session, provider="whoop", owner_id=other_owner) is None
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_failures_count_up_and_a_success_resets_them_and_keeps_the_gap() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.source_poll_cursors import (
        get_poll_cursor,
        record_backfill_failure,
        record_successful_poll,
    )

    engine = _engine()
    owner = uuid4()
    last = datetime(2026, 9, 1, tzinfo=UTC)
    gap = (datetime(2026, 8, 31, tzinfo=UTC), datetime(2026, 9, 9, tzinfo=UTC))
    try:
        async with AsyncSession(engine) as session:
            # No cursor yet: nothing was widened, nothing to count.
            await record_backfill_failure(session, provider="whoop", owner_id=owner)
            assert await get_poll_cursor(session, provider="whoop", owner_id=owner) is None

            await record_successful_poll(session, provider="whoop", owner_id=owner, polled_at=last)
            for _ in range(3):
                await record_backfill_failure(session, provider="whoop", owner_id=owner)
            assert (
                await get_poll_cursor(session, provider="whoop", owner_id=owner)
            ).backfill_failures == 3

            now = datetime(2026, 9, 10, tzinfo=UTC)
            await record_successful_poll(
                session, provider="whoop", owner_id=owner, polled_at=now, unfilled_gap=gap
            )
            await record_successful_poll(
                session, provider="whoop", owner_id=owner, polled_at=now + timedelta(minutes=30)
            )
            cursor = await get_poll_cursor(session, provider="whoop", owner_id=owner)
            assert cursor.backfill_failures == 0
            row = (
                await session.execute(
                    text(
                        "SELECT unfilled_gap_start, unfilled_gap_end FROM source_poll_cursors "
                        "WHERE owner_id = :owner AND provider = 'whoop'"
                    ),
                    {"owner": owner},
                )
            ).one()
            assert (row.unfilled_gap_start, row.unfilled_gap_end) == gap
            await session.rollback()
    finally:
        await engine.dispose()
