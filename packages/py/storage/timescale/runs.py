"""TimescaleDB implementation of :class:`storage.ports.RunRepository`.

Two surfaces for callers:
- :class:`TimescaleRunRepository` — the proper class form. Inject this
  (or any other ``RunRepository`` implementation, including in-memory
  fakes for tests) into consumers that want swappable storage.
- Module-level functions (``claim_run``, ``mark_succeeded``, ...) —
  thin wrappers around :data:`default_repository`. v1.x callers that
  pass an ``AsyncSession`` directly without injecting a repo keep
  working unchanged. New code prefers the class form.

The caller is responsible for committing — both surfaces. Repositories
do not open their own sessions; transaction composition is the caller's
concern. This matches the existing pattern in
``apps/api/server/ingestion/storage.IngestStorage``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PipelineStatus = Literal["pending", "running", "succeeded", "failed", "cancelled", "skipped"]
TriggeredBy = Literal["scheduler", "manual", "api", "event"]


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """Read-side projection of one pipeline_runs row.

    Only the columns callers actually use today. Add fields as
    consumers materialize.
    """

    id: int
    job_kind: str
    idempotency_key: str
    status: PipelineStatus
    started_at: datetime | None
    ended_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    attempt: int
    triggered_by: TriggeredBy


class TimescaleRunRepository:
    """TimescaleDB-backed :class:`storage.ports.RunRepository`.

    Stateless — every method takes the session as an argument. Construct
    once at module import; share the instance across all consumers.
    """

    async def claim_run(
        self,
        session: AsyncSession,
        *,
        job_kind: str,
        idempotency_key: str,
        triggered_by: TriggeredBy = "scheduler",
        leased_by: str | None = None,
    ) -> int | None:
        sql = text(
            """
            INSERT INTO pipeline_runs (
                job_kind, idempotency_key, status,
                started_at, leased_by, leased_at, triggered_by
            )
            VALUES (
                :job_kind, :idempotency_key, 'running',
                now(), :leased_by, now(), :triggered_by
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "job_kind": job_kind,
                "idempotency_key": idempotency_key,
                "leased_by": leased_by,
                "triggered_by": triggered_by,
            },
        )
        row = result.first()
        return row.id if row is not None else None

    async def mark_succeeded(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        result: dict[str, Any] | None = None,
    ) -> None:
        sql = text(
            """
            UPDATE pipeline_runs
               SET status = 'succeeded',
                   ended_at = now(),
                   result = :result
             WHERE id = :run_id
            """
        )
        await session.execute(
            sql,
            {
                "run_id": run_id,
                "result": json.dumps(result) if result is not None else None,
            },
        )

    async def mark_failed(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        error: str,
    ) -> None:
        sql = text(
            """
            UPDATE pipeline_runs
               SET status = 'failed',
                   ended_at = now(),
                   error = :error
             WHERE id = :run_id
            """
        )
        await session.execute(sql, {"run_id": run_id, "error": error[:8000]})

    async def mark_skipped(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        reason: str | None = None,
    ) -> None:
        sql = text(
            """
            UPDATE pipeline_runs
               SET status = 'skipped',
                   ended_at = now(),
                   error = :reason
             WHERE id = :run_id
            """
        )
        await session.execute(sql, {"run_id": run_id, "reason": reason})

    async def lookup_id_by_idempotency_key(
        self,
        session: AsyncSession,
        *,
        idempotency_key: str,
    ) -> int | None:
        """Return the row id for a given idempotency_key, or ``None``.

        Phase 5G lift: previously inlined inside
        ``apps/worker/worker/listener.py`` with a raw ``text(...)``
        call that violated the storage zone invariant under cover of
        the "AsyncSessionFactory typing" allowlist entry.
        """
        sql = text("SELECT id FROM pipeline_runs WHERE idempotency_key = :key")
        row = (await session.execute(sql, {"key": idempotency_key})).first()
        return row.id if row is not None else None

    async def ensure_terminal(
        self,
        session: AsyncSession,
        *,
        job_kind: str,
        idempotency_key: str,
        status: PipelineStatus,
        triggered_by: TriggeredBy = "scheduler",
        leased_by: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> int | None:
        """Set a row's terminal state, creating it if the claim never landed.

        Phase 5G fix for two listener bugs caught in the audit:

        * **Race window** between ``EVENT_JOB_SUBMITTED`` and
          ``EVENT_JOB_EXECUTED``/``EVENT_JOB_ERROR``. Independent
          ``loop.create_task`` dispatches mean a fast job can complete
          before the claim row commits; the old ``_complete`` then
          looked up the row, found nothing, logged a warning, and
          dropped the update — leaving the row absent (next claim
          inserts as ``running``, never updated).
        * **Missed jobs** never persisted. ``EVENT_JOB_MISSED`` should
          write a ``skipped`` row per the listener docstring; pre-5G
          it only logged a warning.

        Implementation: ``INSERT ... ON CONFLICT (idempotency_key) DO
        UPDATE``. The UPDATE branch only sets columns that belong on
        a terminal state — never overwrites the original ``job_kind``
        / ``triggered_by`` / ``started_at`` / ``leased_by``. Returns
        the row id.
        """
        sql = text(
            """
            INSERT INTO pipeline_runs (
                job_kind, idempotency_key, status,
                started_at, ended_at,
                leased_by, leased_at, triggered_by,
                result, error
            )
            VALUES (
                :job_kind, :idempotency_key, :status,
                now(), now(),
                :leased_by, now(), :triggered_by,
                :result, :error
            )
            ON CONFLICT (idempotency_key) DO UPDATE
                SET status = EXCLUDED.status,
                    ended_at = EXCLUDED.ended_at,
                    result = COALESCE(EXCLUDED.result, pipeline_runs.result),
                    error = COALESCE(EXCLUDED.error, pipeline_runs.error)
            RETURNING id
            """
        )
        row = (
            await session.execute(
                sql,
                {
                    "job_kind": job_kind,
                    "idempotency_key": idempotency_key,
                    "status": status,
                    "leased_by": leased_by,
                    "triggered_by": triggered_by,
                    "result": json.dumps(result) if result is not None else None,
                    "error": (error or "")[:8000] or None,
                },
            )
        ).first()
        return row.id if row is not None else None

    async def reap_stuck_runs(
        self,
        session: AsyncSession,
        *,
        max_age_seconds: int,
        error_message: str = "reaped: scheduler listener dropped event",
    ) -> int:
        """Mark every ``status='running'`` row older than the threshold as ``failed``.

        Defends against the listener-drop scenario: an APScheduler event
        was swallowed (loop teardown, exception inside ``_complete``),
        leaving a row stuck ``running`` forever. The reaper closes the
        loop. Returns the number of rows updated so the caller can emit
        a metric or log line proportional to the damage.

        ``max_age_seconds`` is the age threshold. Pass at least 2× the
        longest expected job duration so legitimate long-running jobs
        aren't reaped mid-flight.
        """
        sql = text(
            """
            UPDATE pipeline_runs
               SET status = 'failed',
                   ended_at = now(),
                   error = :error
             WHERE status = 'running'
               AND started_at < now() - make_interval(secs => :max_age_seconds)
            """
        )
        result = await session.execute(
            sql,
            {"error": error_message[:8000], "max_age_seconds": max_age_seconds},
        )
        # ``rowcount`` is supported by both asyncpg and the FakeSession test stubs.
        return getattr(result, "rowcount", 0) or 0

    async def fetch_recent(
        self,
        session: AsyncSession,
        *,
        job_kind: str | None = None,
        limit: int = 100,
    ) -> list[PipelineRun]:
        where = ""
        params: dict[str, Any] = {"limit": limit}
        if job_kind is not None:
            where = "WHERE job_kind = :job_kind"
            params["job_kind"] = job_kind

        sql = text(
            f"""
            SELECT id, job_kind, idempotency_key, status,
                   started_at, ended_at, result, error,
                   attempt, triggered_by
              FROM pipeline_runs
              {where}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).fetchall()
        out: list[PipelineRun] = []
        for r in rows:
            result_payload = r.result
            if isinstance(result_payload, str):
                try:
                    result_payload = json.loads(result_payload)
                except ValueError:
                    result_payload = None
            out.append(
                PipelineRun(
                    id=r.id,
                    job_kind=r.job_kind,
                    idempotency_key=r.idempotency_key,
                    status=r.status,
                    started_at=r.started_at,
                    ended_at=r.ended_at,
                    result=result_payload,
                    error=r.error,
                    attempt=r.attempt,
                    triggered_by=r.triggered_by,
                )
            )
        return out


# Default instance for v1.x callers that haven't migrated to injection.
default_repository = TimescaleRunRepository()


# Module-level convenience wrappers — same signatures as the class
# methods, delegating to ``default_repository``. Existing call sites
# (``await claim_run(session, ...)``) keep working without import-path
# churn beyond ``runtime.runs`` → ``storage.timescale.runs``.


async def claim_run(
    session: AsyncSession,
    *,
    job_kind: str,
    idempotency_key: str,
    triggered_by: TriggeredBy = "scheduler",
    leased_by: str | None = None,
) -> int | None:
    return await default_repository.claim_run(
        session,
        job_kind=job_kind,
        idempotency_key=idempotency_key,
        triggered_by=triggered_by,
        leased_by=leased_by,
    )


async def mark_succeeded(
    session: AsyncSession,
    *,
    run_id: int,
    result: dict[str, Any] | None = None,
) -> None:
    await default_repository.mark_succeeded(session, run_id=run_id, result=result)


async def mark_failed(
    session: AsyncSession,
    *,
    run_id: int,
    error: str,
) -> None:
    await default_repository.mark_failed(session, run_id=run_id, error=error)


async def mark_skipped(
    session: AsyncSession,
    *,
    run_id: int,
    reason: str | None = None,
) -> None:
    await default_repository.mark_skipped(session, run_id=run_id, reason=reason)


async def fetch_recent(
    session: AsyncSession,
    *,
    job_kind: str | None = None,
    limit: int = 100,
) -> list[PipelineRun]:
    return await default_repository.fetch_recent(session, job_kind=job_kind, limit=limit)


async def lookup_id_by_idempotency_key(
    session: AsyncSession,
    *,
    idempotency_key: str,
) -> int | None:
    return await default_repository.lookup_id_by_idempotency_key(
        session, idempotency_key=idempotency_key
    )


async def reap_stuck_runs(
    session: AsyncSession,
    *,
    max_age_seconds: int,
    error_message: str = "reaped: scheduler listener dropped event",
) -> int:
    return await default_repository.reap_stuck_runs(
        session, max_age_seconds=max_age_seconds, error_message=error_message
    )


async def ensure_terminal(
    session: AsyncSession,
    *,
    job_kind: str,
    idempotency_key: str,
    status: PipelineStatus,
    triggered_by: TriggeredBy = "scheduler",
    leased_by: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> int | None:
    return await default_repository.ensure_terminal(
        session,
        job_kind=job_kind,
        idempotency_key=idempotency_key,
        status=status,
        triggered_by=triggered_by,
        leased_by=leased_by,
        result=result,
        error=error,
    )
