"""E2E: a backfill gap the worker gave up on is visible, not only logged.

When a widened source poll keeps failing, the worker polls the default
window again and records the window it gave up on in
source_poll_cursors.unfilled_gap_start/_end. Nothing read those columns: the
only trace was a log line. GET /api/v2/sync/anomalies (an existing read, an
untyped object) now lists them under ``source_backfill_gaps``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.mark.asyncio
async def test_a_given_up_backfill_gap_is_listed_with_the_sync_anomalies() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale import sync_receipts
    from storage.timescale.source_poll_cursors import record_successful_poll

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = "e2e-gap-provider"
    gap_start = datetime(2026, 10, 1, tzinfo=UTC)
    gap_end = gap_start + timedelta(days=9)
    try:
        async with factory() as session:
            before = await sync_receipts.sync_anomalies(session)
            assert not any(
                gap["provider"] == provider for gap in before.get("source_backfill_gaps", [])
            )
            await record_successful_poll(
                session,
                provider=provider,
                polled_at=datetime.now(UTC),
                unfilled_gap=(gap_start, gap_end),
            )
            await session.commit()

            result = await sync_receipts.sync_anomalies(session)

        [gap] = [g for g in result["source_backfill_gaps"] if g["provider"] == provider]
        assert gap["unfilled_from"] == gap_start
        assert gap["unfilled_to"] == gap_end
        assert gap["severity"] == "warning"
        assert "re-authoriz" in gap["recommended_action"] or "export" in gap["recommended_action"]
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM source_poll_cursors WHERE provider = :provider"),
                {"provider": provider},
            )
            await session.commit()
        await engine.dispose()
