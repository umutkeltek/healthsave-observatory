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
