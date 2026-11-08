"""Close ``pipeline_runs`` rows the ledger listener never finished.

The listener inserts a ``running`` row when APScheduler submits a job and
marks it terminal when the job ends. A row whose end event was lost (the
worker stopped mid-job, an exception in the listener) stayed ``running``
forever: ``runs.reap_stuck_runs`` existed, but nothing called it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from .listener import listener_event_mask, make_listener

log = logging.getLogger("healthsave.worker.reaper")

REAPER_JOB_ID = "pipeline_runs_reaper"
# At least twice the longest job (a narrated brief takes minutes), so a slow
# run is never reaped mid-flight.
REAP_AFTER = timedelta(hours=2)
REAP_EVERY = timedelta(minutes=30)


def make_run_reaper(
    session_factory: Any,
    *,
    max_age: timedelta = REAP_AFTER,
) -> Callable[[], Awaitable[int]]:
    """A job that marks ``running`` rows older than ``max_age`` as failed."""

    async def _reap() -> int:
        from storage.timescale import runs

        async with session_factory() as session:
            reaped = await runs.reap_stuck_runs(
                session, max_age_seconds=int(max_age.total_seconds())
            )
            await session.commit()
        if reaped:
            log.warning("reaped %d pipeline_runs row(s) left 'running'", reaped)
        return reaped

    return _reap


def attach_ledger(scheduler: Any, session_factory: Any, *, leased_by: str) -> None:
    """Record every scheduled run in ``pipeline_runs`` and reap the ones left running."""
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_listener(
        make_listener(session_factory, leased_by=leased_by),
        listener_event_mask(),
    )
    scheduler.add_job(
        make_run_reaper(session_factory),
        IntervalTrigger(seconds=int(REAP_EVERY.total_seconds())),
        id=REAPER_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
