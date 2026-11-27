"""E2E: two anomaly checks that overlap persist each anomaly once.

The same run type can run in two places at once: the worker's cron, the
API's trigger routes, and the anomaly check every ingest batch schedules.
A run's ``analysis_runs`` row ('running') and its findings stay in its
open transaction until the run ends, so a second check could not see the
first one: the cooldown read and the existing-anomaly filter only see
committed rows. Both checks then wrote the same anomaly, and
``analysis_findings`` has no unique index to stop the second copy.

Each test feeds the real detector a seeded HRV history (a steady baseline
and one spike at a unique instant), so its findings never collide with
another run's, and holds the first check inside its transaction with an
event while the second one runs. Persistence is real PostgreSQL.

The last test pins the failure path: a run whose transaction a database
error aborted still leaves a 'failed' row, and its lock is released.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


class _SeededHrv:
    """Thirty days of steady HRV, then one spike at ``spike_at``."""

    def __init__(self, spike_at: datetime) -> None:
        self.spike_at = spike_at

    async def fetch_hr_observations(self, start, end):
        return []

    async def fetch_hrv_observations(self, start, end):
        if start <= self.spike_at < end:
            return [(self.spike_at, 140.0)]
        samples = []
        moment = start
        while moment < end:
            samples.append((moment, 48.0 if len(samples) % 2 else 52.0))
            moment += timedelta(hours=12)
        return samples

    async def fetch_workouts(self, start, end):
        return []


def _db_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


def _analysis_engine(db_engine, spike_at):
    from analysis.config import AnalysisConfig
    from analysis.engine import AnalysisEngine
    from analysis.statistical.anomaly import AnomalyDetector
    from sqlalchemy.ext.asyncio import async_sessionmaker

    config = AnalysisConfig()
    # The cooldown would also turn a later check away; 0 keeps this test
    # about the overlap itself and independent of runs other tests left.
    config.analysis.anomaly_detection.cooldown_minutes = 0
    engine = AnalysisEngine(async_sessionmaker(db_engine, expire_on_commit=False), None, config)
    engine.anomaly_detector = AnomalyDetector(_SeededHrv(spike_at), config)
    return engine


async def _max_run_id(db_engine) -> int:
    from sqlalchemy import text

    async with db_engine.connect() as conn:
        return (await conn.execute(text("SELECT COALESCE(max(id), 0) FROM analysis_runs"))).scalar()


async def _spike_findings(db_engine, spike_at) -> int:
    from sqlalchemy import text

    async with db_engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM analysis_findings
                    WHERE finding_type = 'anomaly'
                      AND metric = 'hrv'
                      AND (structured_data->>'detected_at')::timestamptz = :spike_at
                    """
                ),
                {"spike_at": spike_at},
            )
        ).scalar()


async def _runs_since(db_engine, run_id: int) -> list[tuple[int, str]]:
    from sqlalchemy import text

    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id, status
                FROM analysis_runs
                WHERE id > :run_id AND run_type = 'anomaly_check'
                ORDER BY id
                """
            ),
            {"run_id": run_id},
        )
        return [(row.id, row.status) for row in rows]


async def _delete_runs_since(db_engine, run_id: int) -> None:
    from sqlalchemy import text

    async with db_engine.begin() as conn:
        # Findings go with their run (ON DELETE CASCADE).
        await conn.execute(
            text("DELETE FROM analysis_runs WHERE id > :run_id AND run_type = 'anomaly_check'"),
            {"run_id": run_id},
        )


def _unique_spike() -> datetime:
    return datetime.now(tz=UTC) - timedelta(hours=1, microseconds=uuid4().int % 1_000_000)


@pytest.mark.asyncio
async def test_overlapping_anomaly_checks_persist_the_anomaly_once() -> None:
    db_engine = _db_engine()
    spike_at = _unique_spike()
    first = _analysis_engine(db_engine, spike_at)  # e.g. the worker's cron
    second = _analysis_engine(db_engine, spike_at)  # e.g. an ingest-triggered check

    first_filtered = asyncio.Event()
    release_first = asyncio.Event()
    unheld_filter = first._filter_existing_anomalies

    async def held_filter(session, anomalies):
        # The first check has decided what to write and is still inside its
        # transaction when the second check starts.
        kept = await unheld_filter(session, anomalies)
        first_filtered.set()
        await release_first.wait()
        return kept

    first._filter_existing_anomalies = held_filter

    before = await _max_run_id(db_engine)
    try:
        first_run = asyncio.create_task(first.run_anomaly_check())
        await asyncio.wait_for(first_filtered.wait(), timeout=10)

        second_result = await asyncio.wait_for(second.run_anomaly_check(), timeout=10)

        release_first.set()
        first_result = await asyncio.wait_for(first_run, timeout=10)

        assert await _spike_findings(db_engine, spike_at) == 1
        assert isinstance(first_result, int)
        # The second check did no work and says so the way a cooldown skip does.
        assert second_result is None
        assert await _runs_since(db_engine, before) == [(first_result, "completed")]
    finally:
        release_first.set()
        await _delete_runs_since(db_engine, before)
        await db_engine.dispose()


@pytest.mark.asyncio
async def test_a_check_that_raised_does_not_block_the_next_one() -> None:
    db_engine = _db_engine()
    spike_at = _unique_spike()
    failing = _analysis_engine(db_engine, spike_at)
    failing.anomaly_detector.detect = _raise_detector_error
    healthy = _analysis_engine(db_engine, spike_at)

    before = await _max_run_id(db_engine)
    try:
        with pytest.raises(RuntimeError, match="detector exploded"):
            await failing.run_anomaly_check()

        run_id = await asyncio.wait_for(healthy.run_anomaly_check(), timeout=10)

        assert isinstance(run_id, int)
        assert await _spike_findings(db_engine, spike_at) == 1
    finally:
        await _delete_runs_since(db_engine, before)
        await db_engine.dispose()


async def _raise_detector_error(*_args, **_kwargs):
    raise RuntimeError("detector exploded")


@pytest.mark.asyncio
async def test_a_check_that_hit_a_database_error_is_recorded_as_failed() -> None:
    """A database error aborts the run's transaction, so PostgreSQL refused
    the 'failed' UPDATE too and the run vanished: no row said it ever ran."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    db_engine = _db_engine()
    spike_at = _unique_spike()
    missing_table = f"missing_table_{uuid4().hex[:12]}"
    broken = _analysis_engine(db_engine, spike_at)

    async def failing_filter(session, anomalies):
        await session.execute(text(f"SELECT 1 FROM {missing_table}"))

    broken._filter_existing_anomalies = failing_filter
    healthy = _analysis_engine(db_engine, spike_at)

    before = await _max_run_id(db_engine)
    try:
        with pytest.raises(DBAPIError, match=missing_table):
            await broken.run_anomaly_check()

        runs = await _runs_since(db_engine, before)
        assert [status for _run_id, status in runs] == ["failed"]
        async with db_engine.connect() as conn:
            error = (
                await conn.execute(
                    text("SELECT error_message FROM analysis_runs WHERE id = :id"),
                    {"id": runs[0][0]},
                )
            ).scalar()
        assert missing_table in error

        # The lock went with the rolled-back transaction.
        run_id = await asyncio.wait_for(healthy.run_anomaly_check(), timeout=10)
        assert isinstance(run_id, int)
        assert await _spike_findings(db_engine, spike_at) == 1
    finally:
        await _delete_runs_since(db_engine, before)
        await db_engine.dispose()


@pytest.mark.asyncio
async def test_a_run_that_does_not_skip_waits_for_the_run_in_progress_then_runs() -> None:
    """The trigger routes' mode (skip_if_busy=False): wait, then run.

    The waiting run starts only after the first commits, so it sees that
    run's finding and does not write it again.
    """
    db_engine = _db_engine()
    spike_at = _unique_spike()
    first = _analysis_engine(db_engine, spike_at)
    waiting = _analysis_engine(db_engine, spike_at)

    first_filtered = asyncio.Event()
    release_first = asyncio.Event()
    unheld_filter = first._filter_existing_anomalies

    async def held_filter(session, anomalies):
        kept = await unheld_filter(session, anomalies)
        first_filtered.set()
        await release_first.wait()
        return kept

    first._filter_existing_anomalies = held_filter

    before = await _max_run_id(db_engine)
    try:
        first_run = asyncio.create_task(first.run_anomaly_check())
        await asyncio.wait_for(first_filtered.wait(), timeout=10)

        waiting_run = asyncio.create_task(waiting.run_anomaly_check(skip_if_busy=False))
        await asyncio.sleep(0.5)
        assert not waiting_run.done(), "it waits while the first run holds the lock"

        release_first.set()
        first_result = await asyncio.wait_for(first_run, timeout=10)
        waiting_result = await asyncio.wait_for(waiting_run, timeout=10)

        assert isinstance(first_result, int)
        assert waiting_result is None  # it ran and found nothing new
        assert await _spike_findings(db_engine, spike_at) == 1
        runs = await _runs_since(db_engine, before)
        assert [status for _id, status in runs] == ["completed", "skipped"]
    finally:
        release_first.set()
        await _delete_runs_since(db_engine, before)
        await db_engine.dispose()
