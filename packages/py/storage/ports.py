"""Protocol contracts for every storage-backed concern.

Each Protocol is the *shape* an implementation must conform to.
``storage.timescale.*`` provides the v1 TimescaleDB implementations.

Phase 5A defines:
- :class:`RunRepository` — pipeline_runs ledger CRUD.

Phase 5B-D will add:
- ``MeasurementRepository`` (heart_rate, hrv, sleep_*, workouts, ...).
- ``TimeSeriesQueryService`` (Grafana-shaped chart queries, anomalies).
- ``BriefingRepository`` (analysis_runs + analysis_findings + insights).
- ``AgentRunRepository`` (Phase 7).
- ``ExperimentRepository`` (n-of-1 runner, Phase 9+).

Discipline:
- Methods are async.
- Methods take an ``AsyncSession`` argument (passed in by the caller —
  the caller composes transactions; the repository never opens its own
  session). This matches the existing pattern in
  ``apps/api/server/ingestion/storage.IngestStorage``.
- Methods return frozen dataclasses or basic types — never SQLAlchemy
  Row objects, which would leak the ORM into call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .timescale.runs import PipelineRun, TriggeredBy


@runtime_checkable
class RunRepository(Protocol):
    """Pipeline-runs ledger CRUD.

    Idempotency contract: ``claim_run`` is at-most-once via the unique
    constraint on ``idempotency_key`` (returns ``None`` on conflict so
    the caller treats it as 'already done').
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
        """Insert a 'running' row for this scheduled instant.

        Returns the new row id, or ``None`` if a row with the same
        ``idempotency_key`` already exists (caller treats as 'skip').
        """
        ...

    async def mark_succeeded(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        result: dict[str, Any] | None = None,
    ) -> None: ...

    async def mark_failed(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        error: str,
    ) -> None: ...

    async def mark_skipped(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        reason: str | None = None,
    ) -> None: ...

    async def fetch_recent(
        self,
        session: AsyncSession,
        *,
        job_kind: str | None = None,
        limit: int = 100,
    ) -> list[PipelineRun]: ...
