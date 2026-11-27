"""E2E: the data export carries only active rows.

Migration 025 keeps a revised or deleted HealthKit sample as a ``superseded``
row next to its replacement. Every read surface filters those out, but the
export did not, so an export listed both the old and the new value (and
samples the person had deleted in Apple Health).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.mark.asyncio
async def test_superseded_rows_are_not_exported() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.export import default_export_repository as export

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    owner = uuid4()
    try:
        async with AsyncSession(engine) as session:
            device_id = (
                await session.execute(
                    text("INSERT INTO devices (device_type) VALUES (:d) RETURNING id"),
                    {"d": f"e2e export {owner}"},
                )
            ).scalar_one()
            for minute, bpm, status in (
                (0, 70, "superseded"),
                (0, 72, "active"),
                (1, 75, "active"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO heart_rate (time, device_id, bpm, owner_id, status) "
                        "VALUES (:t, :d, :bpm, :owner, :status)"
                    ),
                    {
                        "t": datetime(2026, 9, 3, 7, minute, tzinfo=UTC),
                        "d": device_id,
                        "bpm": bpm,
                        "owner": owner,
                        "status": status,
                    },
                )

            columns, rows = await export.export_metric_rows(
                session, metric="heart_rate", owner_id=owner
            )
            available = {
                entry["metric"]: entry
                for entry in await export.list_available_metrics(session, owner_id=owner)
            }

            bpm = columns.index("bpm")
            assert sorted(row[bpm] for row in rows) == [72, 75]
            assert available["heart_rate"]["count"] == 2
            await session.rollback()
    finally:
        await engine.dispose()
