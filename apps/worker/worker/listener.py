"""APScheduler event listener that records pipeline_runs rows.

The listener is a sync callable APScheduler invokes on the event
loop thread. Each event is dispatched to an async coroutine via
``asyncio.create_task`` so DB writes don't block the scheduler.

Per-event behaviour (Phase 5G — race-safe via INSERT … ON CONFLICT):

  * EVENT_JOB_SUBMITTED  → INSERT a 'running' row (``runs.claim_run``).
  * EVENT_JOB_EXECUTED   → ``runs.ensure_terminal(status='succeeded')``
                          which UPDATEs the claim row OR inserts a
                          terminal row if the claim hasn't committed.
  * EVENT_JOB_ERROR      → same shape, status='failed' with traceback.
  * EVENT_JOB_MISSED     → ``runs.ensure_terminal(status='skipped')``
                          (Phase 5G fix; pre-5G this only logged).

Idempotency key is ``<job_id>:<scheduled_run_time-iso>``. The
upsert pattern means independent ``loop.create_task`` dispatches
of submission + completion can race in either order without
losing the ledger row — the audit found this race in the original
implementation.

Failure observability: every swallowed exception now bumps a
``LEDGER_LISTENER_FAILURES{phase}`` Prometheus counter. Operators
should also run a periodic ``runs.reap_stuck_runs`` to close any
'running' rows the listener never marked terminal (e.g. shutdown
mid-flight).
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


# Counter exposed for ops dashboards. Imported lazily inside the
# listener to keep module import cheap when prometheus_client is
# disabled or absent from the worker image.
def _ledger_listener_failures():
    from server.api.metrics import LEDGER_LISTENER_FAILURES

    return LEDGER_LISTENER_FAILURES


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
                try:
                    _ledger_listener_failures().labels(phase="claim").inc()
                except Exception:  # pragma: no cover - metrics import optional
                    log.debug("failed to record LEDGER_LISTENER_FAILURES{phase=claim}")

    async def _complete(event: JobExecutionEvent, *, succeeded: bool) -> None:
        # Race-safe path: ``ensure_terminal`` is an INSERT … ON CONFLICT
        # DO UPDATE, so it works whether or not ``_claim`` has committed
        # the row yet. Phase 5G fix for the listener race the audit
        # surfaced — independent ``loop.create_task`` dispatches mean a
        # fast job can complete before its claim row commits; pre-5G
        # ``_complete`` would log "no pipeline_run row" and drop the
        # update.
        async with session_factory() as session:
            try:
                key = _idempotency_key(event.job_id, event.scheduled_run_time)
                if succeeded:
                    result = _coerce_result(event.retval)
                    error = None
                    status: runs.PipelineStatus = "succeeded"
                else:
                    result = None
                    error = str(event.exception) if event.exception is not None else "unknown error"
                    status = "failed"
                await runs.ensure_terminal(
                    session,
                    job_kind=event.job_id,
                    idempotency_key=key,
                    status=status,
                    triggered_by="scheduler",
                    leased_by=leased_by,
                    result=result,
                    error=error,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("failed to mark pipeline_run for %s", event.job_id)
                try:
                    _ledger_listener_failures().labels(
                        phase="mark_succeeded" if succeeded else "mark_failed"
                    ).inc()
                except Exception:  # pragma: no cover - metrics import optional
                    log.debug("failed to record LEDGER_LISTENER_FAILURES{phase=mark_*}")

    async def _missed(event: Any) -> None:
        # Phase 5G fix for an audit finding: pre-5G ``EVENT_JOB_MISSED``
        # only emitted log.warning despite the listener docstring
        # promising a ``skipped`` ledger row. Use ``ensure_terminal`` so
        # the row exists regardless of whether a claim landed first.
        async with session_factory() as session:
            try:
                key = _idempotency_key(event.job_id, event.scheduled_run_time)
                await runs.ensure_terminal(
                    session,
                    job_kind=event.job_id,
                    idempotency_key=key,
                    status="skipped",
                    triggered_by="scheduler",
                    leased_by=leased_by,
                    error=f"missed scheduled run at {event.scheduled_run_time}",
                )
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("failed to record missed pipeline_run for %s", event.job_id)
                try:
                    _ledger_listener_failures().labels(phase="missed").inc()
                except Exception:  # pragma: no cover - metrics import optional
                    log.debug("failed to record LEDGER_LISTENER_FAILURES{phase=missed}")

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
            loop.create_task(_missed(event))

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


def _coerce_result(retval: Any) -> dict[str, Any] | None:
    """Best-effort projection of an arbitrary job return value into a JSON object."""
    if retval is None:
        return None
    if isinstance(retval, dict):
        return retval
    if isinstance(retval, int):
        return {"value": retval}
    return {"repr": repr(retval)[:1000]}
