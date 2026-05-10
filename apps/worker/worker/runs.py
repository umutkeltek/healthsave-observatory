"""Data access for the pipeline_runs ledger.

Functions are async, take an SQLAlchemy ``AsyncSession`` (so a caller
can compose them into existing transactions if needed) and use
``sqlalchemy.text`` like the rest of the project. They write to one
table only — ``pipeline_runs`` — and never touch APScheduler internals
or the analysis engine.

The caller is responsible for committing. The worker's APScheduler
listener wraps each event in its own short-lived transaction.
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


async def claim_run(
    session: AsyncSession,
    *,
    job_kind: str,
    idempotency_key: str,
    triggered_by: TriggeredBy = "scheduler",
    leased_by: str | None = None,
) -> int | None:
    """Insert a new pending row, marking it running and returning its id.

    Returns ``None`` if a row with this idempotency_key already exists
    (the caller treats this as 'already done; skip'). The unique
    constraint on idempotency_key enforces the at-most-once contract.
    """
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
        {"run_id": run_id, "result": json.dumps(result) if result is not None else None},
    )


async def mark_failed(
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
    session: AsyncSession,
    *,
    job_kind: str | None = None,
    limit: int = 100,
) -> list[PipelineRun]:
    """List recent runs newest-first. Used by /api/insights and ops UIs."""
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
