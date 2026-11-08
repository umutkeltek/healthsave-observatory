"""E2E: one failed per-metric query no longer zeroes the rest of the response.

``/api/apple/status`` and ``/api/apple/coverage`` run one query per metric
and degrade a failing metric to an empty value (the frozen shape stays). On
PostgreSQL the failed statement aborts the transaction, so without a rollback
every later query in the loop failed too and reported zeros/None. A mocked
session cannot show this; these tests run the handlers on a real database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


class _FirstQueryAborts:
    """Real session; the first query aborts the transaction and raises."""

    def __init__(self, session) -> None:
        self._session = session
        self._failed = False

    async def execute(self, statement, params=None):
        if not self._failed:
            self._failed = True
            from sqlalchemy import text

            await self._session.execute(text("SELECT 1 / 0"))
        return await self._session.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self._session, name)


def _request(owner) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"x-user-id": str(owner)},
        state=SimpleNamespace(),
    )


async def _seed(session, owner) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            "INSERT INTO workouts (sport_type, start_time, end_time, owner_id) "
            "VALUES ('Running', :start, :end, :owner)"
        ),
        {
            "start": datetime(2026, 9, 1, 7, 0, tzinfo=UTC),
            "end": datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
            "owner": owner,
        },
    )


@pytest.mark.asyncio
async def test_status_keeps_reporting_after_one_metric_query_fails(monkeypatch) -> None:
    from server.api.status import apple_status
    from server.ingestion import owner as owner_module
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    monkeypatch.setattr(owner_module, "ALLOW_MULTI_USER", True)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    try:
        async with AsyncSession(engine) as seed:
            await _seed(seed, owner)
            await seed.commit()
        async with AsyncSession(engine) as session:
            status = await apple_status(_request(owner), _FirstQueryAborts(session))

        assert status["heart_rate"] == {"count": 0, "oldest": None, "newest": None}
        assert status["workouts"]["count"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_coverage_keeps_reporting_after_one_metric_query_fails(monkeypatch) -> None:
    from server.api.coverage import apple_coverage
    from server.ingestion import owner as owner_module
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    monkeypatch.setattr(owner_module, "ALLOW_MULTI_USER", True)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    try:
        async with AsyncSession(engine) as seed:
            await _seed(seed, owner)
            await seed.commit()
        async with AsyncSession(engine) as session:
            coverage = await apple_coverage(_request(owner), _FirstQueryAborts(session))

        assert coverage["workouts"] is not None
    finally:
        await engine.dispose()
