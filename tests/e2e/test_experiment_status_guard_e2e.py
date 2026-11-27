"""E2E: an analyze run never completes an experiment that was abandoned meanwhile.

``ExperimentRunner.run_controlled`` decided "collecting -> completed" from the
row it read at the start and then wrote the status unconditionally. An abandon
that landed in between was overwritten with "completed".
"""

from __future__ import annotations

import os
from datetime import date

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


@pytest.mark.asyncio
async def test_a_stale_analyze_does_not_complete_an_abandoned_experiment() -> None:
    from analysis.experiments import ExperimentRunner
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale.experiments import default_repository as experiments

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            row = await experiments.create_experiment(
                session,
                lever_metric_id="activity.steps",
                outcome_metric_id="vital.resting_heart_rate",
                design="ABAB",
                block_days=1,
                start_date=date(2025, 1, 1),  # window long over: analyze completes it
            )
            await session.commit()

        stale = row  # what an analyze request read before the abandon landed
        async with factory() as session:
            await experiments.set_status(session, experiment_id=row.id, status="abandoned")
            await session.commit()

        await ExperimentRunner(factory).run_controlled(stale, as_of=date(2026, 11, 8))

        async with factory() as session:
            current = await experiments.get_experiment(session, experiment_id=row.id)
        assert current.status == "abandoned"
    finally:
        await engine.dispose()
