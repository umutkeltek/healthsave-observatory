"""E2E: sync coverage never claims samples from a failed batch were stored.

Day-total metrics store one row per day at midnight, so coverage reports the
latest *receipt* sample time for a stored day (GH#14). That receipt time came
from every receipt, failed ones included: a failed steps batch late in the day
made coverage say the whole day through that time was stored.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]

_RECEIPT = """
    INSERT INTO healthsave_sync_receipts
        (owner_id, metric, status, records_received, records_accepted,
         sample_min_at, sample_max_at, received_at, completed_at)
    VALUES (:owner_id, 'step_count', :status, 1, :accepted,
            :sample_min_at, :sample_max_at, now(), now())
"""


@pytest.mark.asyncio
async def test_a_failed_batch_does_not_extend_day_total_coverage() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.sync_receipts import sync_coverage

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    day = date(2026, 9, 1)
    try:
        async with AsyncSession(engine) as session:
            device_id = (
                await session.execute(
                    text("INSERT INTO devices (device_type) VALUES (:d) RETURNING id"),
                    {"d": f"e2e coverage {owner}"},
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO daily_activity (date, device_id, steps, owner_id) "
                    "VALUES (:day, :device_id, 4200, :owner_id)"
                ),
                {"day": day, "device_id": device_id, "owner_id": owner},
            )
            stored_through = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
            failed_through = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
            await session.execute(
                text(_RECEIPT),
                {
                    "owner_id": owner,
                    "status": "processed",
                    "accepted": 1,
                    "sample_min_at": datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                    "sample_max_at": stored_through,
                },
            )
            await session.execute(
                text(_RECEIPT),
                {
                    "owner_id": owner,
                    "status": "failed",
                    "accepted": 0,
                    "sample_min_at": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
                    "sample_max_at": failed_through,
                },
            )

            coverage = await sync_coverage(session, owner_id=owner)
            steps = next(row for row in coverage["metrics"] if row["metric"] == "step_count")

            assert steps["batches_failed"] == 1
            assert steps["latest_destination_sample_time"] == stored_through
            assert steps["receipt_sample_window"]["max_sample_time"] == stored_through
            await session.rollback()
    finally:
        await engine.dispose()
