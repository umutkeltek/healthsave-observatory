"""Real PostgreSQL regression for overlapping UUID revisions of one active slot."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.measurements import _ingest_dedicated

DATABASE_URL = os.getenv("E2E_DATABASE_URL")
OWNER = UUID("00000000-0000-0000-0000-000000000001")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL for real PostgreSQL proof"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_row", [False, True], ids=["empty-slot", "revised-slot"])
async def test_concurrent_uuid_revisions_do_not_reject_the_batch(existing_row: bool) -> None:
    """Hold one revision uncommitted until another writer waits on its slot.

    With an existing row, the second UPDATE's snapshot sees the original but
    cannot see the first writer's replacement. Without one, both UPDATEs find
    nothing. In either case the second INSERT used to collide with the active
    slot index after the first transaction committed.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
    device_name = f"e2e concurrent revision {uuid4()}"
    sample_time = datetime(2026, 9, 25, 8, 43, tzinfo=UTC)
    original_uuid, first_uuid, second_uuid = (str(uuid4()) for _ in range(3))

    def sample(uid: str, value: int) -> dict:
        return {"date": sample_time.isoformat(), "qty": value, "uuid": uid, "source": device_name}

    second_task = None
    try:
        device_id = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id", device_name
        )
        if existing_row:
            async with AsyncSession(engine) as seed:
                await _ingest_dedicated(seed, device_id, "heart_rate", [sample(original_uuid, 70)])
                await seed.commit()

        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await _ingest_dedicated(first, device_id, "heart_rate", [sample(first_uuid, 72)])
            second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

            async def write_second() -> None:
                await _ingest_dedicated(second, device_id, "heart_rate", [sample(second_uuid, 75)])
                await second.commit()

            second_task = asyncio.create_task(write_second())
            try:
                async with asyncio.timeout(10):
                    while not second_task.done():
                        wait_type = await conn.fetchval(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = $1",
                            second_pid,
                        )
                        if wait_type == "Lock":
                            break
                        await asyncio.sleep(0.01)
                    assert not second_task.done(), "second writer must overlap the open transaction"
            finally:
                # Always release our synthetic transaction, including a failed assertion.
                await first.commit()
                await second_task

        rows = await conn.fetch(
            "SELECT source_uuid, status FROM heart_rate "
            "WHERE time = $1 AND device_id = $2 AND owner_id = $3",
            sample_time,
            device_id,
            OWNER,
        )
        assert [str(r["source_uuid"]) for r in rows if r["status"] == "active"] == [second_uuid]

        # A delayed outbox replay must not bring the older revision back to life.
        async with AsyncSession(engine) as replay:
            await _ingest_dedicated(replay, device_id, "heart_rate", [sample(first_uuid, 72)])
            await replay.commit()
        active_uuid = await conn.fetchval(
            "SELECT source_uuid FROM heart_rate "
            "WHERE time = $1 AND device_id = $2 AND owner_id = $3 AND status = 'active'",
            sample_time,
            device_id,
            OWNER,
        )
        assert str(active_uuid) == second_uuid
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        await engine.dispose()
        await conn.close()
