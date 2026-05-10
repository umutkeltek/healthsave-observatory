"""APScheduler event listener that records pipeline_runs rows.

The listener is a sync callable APScheduler invokes on the event
loop thread. Each event is dispatched to an async coroutine via
``asyncio.create_task`` so DB writes don't block the scheduler.

One job invocation produces 1-2 rows depending on event timing:
  * EVENT_JOB_SUBMITTED  → INSERT a 'running' row (claim)
  * EVENT_JOB_EXECUTED   → UPDATE to 'succeeded' (with retval)
  * EVENT_JOB_ERROR      → UPDATE to 'failed' (with traceback)
  * EVENT_JOB_MISSED     → INSERT a 'skipped' row directly

Idempotency key is ``<job_id>:<scheduled_run_time-iso>``. Two events
for the same scheduled instant resolve to the same row.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import async_sessionmaker
from storage.timescale import runs

if TYPE_CHECKING:
    from apscheduler.events import JobExecutionEvent, JobSubmissionEvent

log = logging.getLogger("healthsave.worker.listener")


def _idempotency_key(job_id: str, scheduled_run_time: Any) -> str:
    """Stable id per scheduled instant.

    APScheduler events expose ``scheduled_run_times`` as a list (since
    coalesce can fold multiple ticks into one). We use the first.
    """
    if isinstance(scheduled_run_time, list):
        scheduled_run_time = scheduled_run_time[0] if scheduled_run_time else None
    iso = scheduled_run_time.isoformat() if scheduled_run_time is not None else "now"
    return f"{job_id}:{iso}"


def make_listener(
    session_factory: async_sessionmaker,
    *,
    leased_by: str | None = None,
):
    """Build a sync listener bound to a session factory + lease identity."""

    async def _claim(event: JobSubmissionEvent) -> None:
        async with session_factory() as session:
            try:
                await runs.claim_run(
                    session,
                    job_kind=event.job_id,
                    idempotency_key=_idempotency_key(event.job_id, event.scheduled_run_times),
                    triggered_by="scheduler",
                    leased_by=leased_by,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("failed to claim pipeline_run for %s", event.job_id)

    async def _complete(event: JobExecutionEvent, *, succeeded: bool) -> None:
        async with session_factory() as session:
            try:
                key = _idempotency_key(event.job_id, event.scheduled_run_time)
                run_id = await _lookup_run_id(session, key)
                if run_id is None:
                    log.warning(
                        "no pipeline_run row for %s key=%s; skipping mark", event.job_id, key
                    )
                    return
                if succeeded:
                    result = _coerce_result(event.retval)
                    await runs.mark_succeeded(session, run_id=run_id, result=result)
                else:
                    error = str(event.exception) if event.exception is not None else "unknown error"
                    await runs.mark_failed(session, run_id=run_id, error=error)
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("failed to mark pipeline_run for %s", event.job_id)

    def listener(event: Any) -> None:
        from apscheduler.events import (
            EVENT_JOB_ERROR,
            EVENT_JOB_EXECUTED,
            EVENT_JOB_MISSED,
            EVENT_JOB_SUBMITTED,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("no running loop; cannot record event %s", event.code)
            return

        if event.code == EVENT_JOB_SUBMITTED:
            loop.create_task(_claim(event))
        elif event.code == EVENT_JOB_EXECUTED:
            loop.create_task(_complete(event, succeeded=True))
        elif event.code == EVENT_JOB_ERROR:
            loop.create_task(_complete(event, succeeded=False))
        elif event.code == EVENT_JOB_MISSED:
            log.warning("job missed: %s scheduled=%s", event.job_id, event.scheduled_run_time)

    return listener


def listener_event_mask() -> int:
    """The bitmask of events the worker subscribes to."""
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
        EVENT_JOB_SUBMITTED,
    )

    return EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED


async def _lookup_run_id(session, key: str) -> int | None:
    from sqlalchemy import text

    sql = text("SELECT id FROM pipeline_runs WHERE idempotency_key = :key")
    row = (await session.execute(sql, {"key": key})).first()
    return row.id if row is not None else None


def _coerce_result(retval: Any) -> dict[str, Any] | None:
    """Best-effort projection of an arbitrary job return value into a JSON object."""
    if retval is None:
        return None
    if isinstance(retval, dict):
        return retval
    if isinstance(retval, int):
        return {"value": retval}
    return {"repr": repr(retval)[:1000]}
