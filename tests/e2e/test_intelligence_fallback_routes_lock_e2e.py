"""E2E: two saves of the narrator fallback chain for one owner take turns.

``set_fallback_routes`` replaces the chain with DELETE then INSERT. Two saves
running at once used to interleave: the second save's DELETE could not see
the first save's uncommitted rows, so its INSERT hit
``uq_llm_fallback_owner_priority`` (a 500), or, when the old chain was
non-empty, its DELETE skipped the rows the first save had already removed and
the first save's new chain survived a later clear. The replacement now takes
a per-owner transaction lock, so the second save starts from the first one's
committed chain. Only real PostgreSQL shows this; a mocked session cannot.
"""

from __future__ import annotations

import asyncio
import os
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


async def _connections(engine, owner) -> tuple[int, int]:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import default_repository

    async with AsyncSession(engine) as session:
        first = await default_repository.upsert_connection(
            session, provider="e2e-first", destination="local", owner_id=owner
        )
        second = await default_repository.upsert_connection(
            session, provider="e2e-second", destination="local", owner_id=owner
        )
        await session.commit()
    return first.id, second.id


async def _wait_until_blocked(engine, pid: int) -> None:
    """Return once backend ``pid`` waits on a lock (or after ~5 s)."""
    from sqlalchemy import text

    for _ in range(100):
        async with engine.connect() as conn:
            waiting = (
                await conn.execute(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": pid},
                )
            ).scalar()
        if waiting == "Lock":
            return
        await asyncio.sleep(0.05)


async def _race(engine, owner, first_routes, second_routes) -> None:
    """Save ``first_routes`` and hold the transaction; save ``second_routes``
    concurrently; commit the first; let the second finish."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import default_repository

    async with AsyncSession(engine) as first, AsyncSession(engine) as second:
        await default_repository.set_fallback_routes(first, routes=first_routes, owner_id=owner)
        second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

        async def second_save() -> None:
            await default_repository.set_fallback_routes(
                second, routes=second_routes, owner_id=owner
            )
            await second.commit()

        task = asyncio.create_task(second_save())
        await _wait_until_blocked(engine, second_pid)
        assert not task.done(), "the second save must wait for the first"
        await first.commit()
        await asyncio.wait_for(task, timeout=10)


async def _chain(engine, owner) -> list[tuple[int, int, str]]:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import default_repository

    async with AsyncSession(engine) as session:
        routes = await default_repository.get_fallback_routes(session, owner_id=owner)
    return [(route.priority, route.connection_id, route.model) for route in routes]


async def _cleanup(engine, owner) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM llm_fallback_routes WHERE owner_id = :owner"), {"owner": str(owner)}
        )
        await conn.execute(
            text("DELETE FROM llm_connections WHERE owner_id = :owner"), {"owner": str(owner)}
        )


@pytest.mark.asyncio
async def test_concurrent_chain_saves_do_not_collide_on_priority() -> None:
    from storage.timescale.intelligence import FallbackRouteInput

    engine = _engine()
    owner = uuid4()
    try:
        first_id, second_id = await _connections(engine, owner)

        await _race(
            engine,
            owner,
            [
                FallbackRouteInput(connection_id=first_id, model="first-0"),
                FallbackRouteInput(connection_id=first_id, model="first-1"),
            ],
            [FallbackRouteInput(connection_id=second_id, model="second-0")],
        )

        # The later save wins whole; no unique violation, no leftover rows.
        assert await _chain(engine, owner) == [(0, second_id, "second-0")]
    finally:
        await _cleanup(engine, owner)
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_clear_saved_after_a_concurrent_replace_is_not_lost() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import FallbackRouteInput, default_repository

    engine = _engine()
    owner = uuid4()
    try:
        first_id, _second_id = await _connections(engine, owner)
        async with AsyncSession(engine) as session:
            await default_repository.set_fallback_routes(
                session,
                routes=[
                    FallbackRouteInput(connection_id=first_id, model=f"old-{i}") for i in range(3)
                ],
                owner_id=owner,
            )
            await session.commit()

        await _race(
            engine,
            owner,
            [FallbackRouteInput(connection_id=first_id, model="replaced-0")],
            [],
        )

        # The clear committed last, so the chain is empty.
        assert await _chain(engine, owner) == []
    finally:
        await _cleanup(engine, owner)
        await engine.dispose()
