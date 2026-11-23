"""E2E: analysis never averages two devices into one number (real PostgreSQL).

Whoop's resting heart rate now reaches the canonical store beside the Apple
Watch's. The weekly brief, the recovery score and the correlations read
``summarize_metric_window`` and ``fetch_metric_daily_series``; before this
change they averaged every source of a metric, so an Apple Watch at 60 bpm and
a Whoop at 50 bpm on the same days read as 55, a number neither device
measured. Each read now uses one stream. Seeded far in the future for a
throwaway owner, inside one transaction that is rolled back.
"""

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

DAY0 = datetime(2031, 3, 1, 6, 0, tzinfo=UTC)


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


def _apple_rhr(owner, day: int, bpm: float):
    from contracts._base import Provenance
    from normalization import normalize_apple_batch

    at = (DAY0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    result = normalize_apple_batch(
        {
            "metric": "resting_heart_rate",
            "samples": [
                {
                    "uuid": str(uuid4()).upper(),
                    "startDate": at,
                    "endDate": at,
                    "date": at,
                    "qty": bpm,
                    "unit": "count/min",
                    "source": "Apple Watch",
                }
            ],
        },
        source_id=uuid4(),
        provenance=Provenance(
            source_plugin_id="apple_health", sdk_version="e2e", captured_at=datetime.now(UTC)
        ),
        owner_id=owner,
    )
    assert result.accepted == 1, result.rejections
    return result.observations


@pytest.mark.asyncio
async def test_apple_watch_and_whoop_resting_heart_rate_are_never_averaged() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.analysis import fetch_metric_daily_series, summarize_metric_window
    from storage.timescale.observations import CanonicalObservationRepository

    from plugins.sources.whoop.normalize import recovery_observation

    owner = uuid4()
    repo = CanonicalObservationRepository()
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            observations = []
            # Apple Watch reads 60 bpm on 6 days; Whoop reads 50 bpm on 4 of them.
            for day in range(6):
                observations += _apple_rhr(owner, day, 60.0)
            for day in range(4):
                obs = recovery_observation(
                    owner_id=owner,
                    metric_id="vital.resting_heart_rate",
                    value=50.0,
                    at=DAY0 + timedelta(days=day, minutes=5),
                )
                assert obs is not None
                observations.append(obs)
            await repo.insert_many(session, observations)

            start, end = DAY0 - timedelta(days=1), DAY0 + timedelta(days=7)
            window = await summarize_metric_window(
                session, "vital.resting_heart_rate", start, end, owner_id=owner
            )
            daily = await fetch_metric_daily_series(
                session, "vital.resting_heart_rate", start, end, owner_id=owner
            )
            await session.rollback()
    finally:
        await engine.dispose()

    # One device, the one with more readings: never 55, never a mixed count.
    assert window == {"avg": 60.0, "min": 60.0, "max": 60.0, "count": 6}
    assert [row.value for row in daily] == [60.0] * 6
