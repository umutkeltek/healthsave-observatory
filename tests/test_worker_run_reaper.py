"""The worker reaps pipeline_runs rows the ledger listener never finished.

``runs.reap_stuck_runs`` had no caller, so a row left ``running`` (worker
stopped mid-job, a lost listener event) stayed ``running`` forever.
"""

from __future__ import annotations

from typing import Any

import pytest
from worker import reaper


class _Scheduler:
    def __init__(self) -> None:
        self.listeners: list[Any] = []
        self.jobs: list[dict[str, Any]] = []

    def add_listener(self, callback, mask) -> None:
        self.listeners.append(callback)

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


def test_attaching_the_ledger_schedules_the_reaper() -> None:
    scheduler = _Scheduler()

    reaper.attach_ledger(scheduler, lambda: _Session(), leased_by="host:1")

    assert len(scheduler.listeners) == 1
    [job] = scheduler.jobs
    assert job["id"] == reaper.REAPER_JOB_ID
    assert job["max_instances"] == 1


def test_the_worker_attaches_the_ledger_through_the_reaping_seam() -> None:
    from worker import main

    assert main.attach_ledger is reaper.attach_ledger


@pytest.mark.asyncio
async def test_the_reaper_fails_rows_running_longer_than_the_threshold(monkeypatch) -> None:
    from storage.timescale import runs

    calls: list[int] = []

    async def reap_stuck_runs(session, *, max_age_seconds, **_kwargs):
        calls.append(max_age_seconds)
        return 2

    monkeypatch.setattr(runs, "reap_stuck_runs", reap_stuck_runs)
    session = _Session()

    reaped = await reaper.make_run_reaper(lambda: session)()

    assert reaped == 2
    assert calls == [int(reaper.REAP_AFTER.total_seconds())]
    assert session.commits == 1
