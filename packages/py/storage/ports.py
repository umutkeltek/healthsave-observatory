"""Protocol contracts for every storage-backed concern.

Each Protocol is the *shape* an implementation must conform to.
``storage.timescale.*`` provides the v1 TimescaleDB implementations.

Defined ports:
- :class:`RunRepository` (Phase 5A) — pipeline_runs ledger CRUD.
- :class:`BriefingRepository` (Phase 5B) — analysis_insights /
  analysis_findings reads.
- :class:`IngestStorage` (Phase 5C, relocated) — write side of the
  ingest pipeline. The shape is unchanged from v1.
- :class:`AuditLog` (Phase 5C, relocated) — optional raw-payload
  audit; Postgres-only, InfluxDB-style backends skip.
- :class:`MeasurementRepository` (Phase 5C, skeleton) — placeholder
  Protocol that Phase 5D fills in as per-metric SQL migrates out of
  ``server.ingestion.handlers``.
- :class:`TimeSeriesQueryService` (Phase 5D) — read port for metric
  time-series, satisfied by
  ``storage.timescale.observations.CanonicalObservationRepository``. The
  seam the analysis engine, the v2 read API, and the n-of-1 runner share.
- :class:`ExperimentRepository` (n-of-1 engine) — CRUD for committed ABAB
  experiments + the analysis results the runtime computes against them,
  reading time-series through the port above. Impl:
  ``storage.timescale.experiments.TimescaleExperimentRepository``.

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
    from collections.abc import Iterable
    from datetime import date, datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from .results import IngestWriteResult
    from .timescale.agents import (
        ActionKind,
        ArtifactKind,
        DecidedBy,
        Decision,
        EventKind,
        ExecutionStatus,
        ProposalRow,
        RunStatus,
        TriggerKind,
    )
    from .timescale.briefings import FindingRow, NarrativeRow
    from .timescale.experiments import ExperimentResultRow, ExperimentRow
    from .timescale.observations import SeriesPoint
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


@runtime_checkable
class BriefingRepository(Protocol):
    """Read-side data access for the analysis surface.

    Reads ``analysis_insights`` (latest narratives) and
    ``analysis_findings`` (anomalies, trends). Wire-shape mapping
    happens in the API route handler — this Protocol returns the
    storage-shaped frozen dataclasses ``NarrativeRow`` and
    ``FindingRow``.

    Inputs are assumed pre-validated. The route handler rejects
    unknown severity values, malformed ``since`` timestamps, and
    bad ``period`` strings *before* calling these methods.
    """

    async def latest_narratives_by_type(
        self,
        session: AsyncSession,
        *,
        insight_types: Iterable[str] = ("daily_briefing", "weekly_summary"),
    ) -> dict[str, NarrativeRow]: ...

    async def fetch_anomalies(
        self,
        session: AsyncSession,
        *,
        since: datetime | None = None,
        severities: Iterable[str] | None = None,
        limit: int = 200,
    ) -> list[FindingRow]: ...

    async def fetch_trends(
        self,
        session: AsyncSession,
        *,
        period_days: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]: ...

    async def fetch_correlations(
        self,
        session: AsyncSession,
        *,
        period_days: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]: ...

    async def fetch_findings(
        self,
        session: AsyncSession,
        *,
        finding_type: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]: ...


@runtime_checkable
class IngestStorage(Protocol):
    """Minimum surface every ingest backend must implement.

    Backend-agnostic by design — ``session`` is ``Any`` so a backend
    can use a SQLAlchemy ``AsyncSession``, an httpx client, or nothing
    at all. TimescaleDB returns ``int`` device ids; InfluxDB-style
    backends can return the device_type string (identity flows through
    tags). Both shapes satisfy ``int | str``.
    """

    async def get_or_create_device(self, session: Any, device_type: str) -> int | str: ...

    async def ingest_metric(
        self,
        session: Any,
        device_id: int | str,
        metric: str,
        samples: list[dict],
        owner_id: UUID,
    ) -> int | IngestWriteResult: ...


@runtime_checkable
class AuditLog(Protocol):
    """Optional: persist + mark raw ingest payloads.

    Postgres-shaped concern — auto-incrementing id, UPDATE on a
    ``processed`` column. Append-only backends like InfluxDB don't
    need to implement it; the route falls back to skipping audit
    calls when ``app.state.audit_log`` is ``None``.
    """

    async def log_raw(
        self,
        session: Any,
        device_id: int | str | None,
        raw_payload: dict,
    ) -> Any: ...

    async def mark_processed(self, session: Any, raw_log_id: Any) -> None: ...


@runtime_checkable
class MeasurementRepository(Protocol):
    """Per-metric measurement storage. Skeleton for Phase 5D.

    Today this Protocol intentionally requires zero methods — the
    handler-level SQL hasn't been lifted yet. The empty Protocol
    provides the binding type so consumers can begin to depend on
    ``storage.ports.MeasurementRepository`` and tests can build fake
    in-memory implementations against the same name. Phase 5D adds
    real methods (``insert_heart_rate``, ``insert_workout``,
    ``fetch_series``, etc.) as their SQL migrates here.
    """


@runtime_checkable
class TimeSeriesQueryService(Protocol):
    """Read port for metric time-series.

    The seam the analysis engine, the v2 read API, and the (future)
    :class:`ExperimentRepository` all query. Satisfied today by
    :class:`storage.timescale.observations.CanonicalObservationRepository`
    with no changes — formalizing the port lets consumers depend on the
    abstraction and inject in-memory fakes in tests instead of reaching
    into the concrete TimescaleDB repo.

    Returns storage-shaped
    :class:`~storage.timescale.observations.SeriesPoint` dataclasses,
    never ORM rows. Stateless — the caller owns the session/transaction,
    matching every other read port in this module. The window is
    half-open ``[start, end)`` and results are ascending by ``t``.
    """

    async def query_series(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        metric_id: str,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[SeriesPoint]: ...


@runtime_checkable
class ReadinessRepository(Protocol):
    """Read-side coverage for the v2 data-readiness surface."""

    async def fetch_canonical_coverage(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> list[dict[str, Any]]: ...

    async def fetch_canonical_sources(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class AgentRepository(Protocol):
    """AgentRun ledger CRUD — six Phase 7-A tables behind one Protocol.

    Phase 7-C's supervisor and Phase 7-E's API routes depend on this
    Protocol; the TimescaleDB impl is :class:`storage.timescale.agents.TimescaleAgentRepository`.
    Tests build in-memory fakes against the same shape.

    Idempotency contract on :meth:`propose_action`: when
    ``idempotency_key`` is provided and a row with the same key
    already exists, the method returns ``None`` (the caller treats
    this as 'already proposed, do not re-emit downstream events').
    When ``idempotency_key`` is ``None``, the row always lands.

    Transaction discipline: every method takes ``AsyncSession`` and
    NEVER calls ``commit()`` — the caller composes multiple writes
    into one transaction (e.g. ``start_run`` + ``record_event``
    'run_started') and commits once.
    """

    async def start_run(
        self,
        session: AsyncSession,
        *,
        plugin_id: str,
        trigger_kind: TriggerKind,
        trigger_metadata: dict[str, Any] | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID: ...

    async def mark_run_terminal(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> None: ...

    async def propose_action(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        action_kind: ActionKind,
        payload: dict[str, Any],
        rationale: str,
        capability: str,
        idempotency_key: str | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID | None: ...

    async def decide_action(
        self,
        session: AsyncSession,
        *,
        proposal_id: UUID,
        decision: Decision,
        decided_by: DecidedBy,
        rationale: str | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID: ...

    async def execute_action(
        self,
        session: AsyncSession,
        *,
        proposal_id: UUID,
        decision_id: UUID,
        status: ExecutionStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID: ...

    async def record_event(
        self,
        session: AsyncSession,
        *,
        run_id: UUID | None,
        kind: EventKind,
        payload: dict[str, Any] | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID: ...

    async def record_artifact(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        kind: ArtifactKind,
        payload: dict[str, Any],
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> UUID: ...

    async def fetch_recent_proposals(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = ...,
        limit: int = 50,
        undecided_only: bool = False,
    ) -> list[ProposalRow]: ...


@runtime_checkable
class ExperimentRepository(Protocol):
    """CRUD for the n-of-1 experiment engine.

    Persists committed ABAB experiment definitions (lever, outcome, design,
    schedule, status) and the analysis results the runtime computes against
    them. Reads the underlying time-series through
    :class:`TimeSeriesQueryService`; the pure statistics live in
    ``analysis.statistical.experiments`` and the orchestration in
    ``analysis.experiments`` — this port only reads and writes rows.

    Impl: :class:`storage.timescale.experiments.TimescaleExperimentRepository`.
    Returns frozen ``ExperimentRow`` / ``ExperimentResultRow`` dataclasses, never
    ORM rows. Stateless — the caller owns the session/transaction and commits.
    """

    async def create_experiment(
        self,
        session: AsyncSession,
        *,
        lever_metric_id: str,
        outcome_metric_id: str,
        design: str,
        block_days: int,
        start_date: date,
        hypothesis: str | None = None,
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> ExperimentRow: ...

    async def get_experiment(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
        owner_id: UUID = ...,
    ) -> ExperimentRow | None: ...

    async def list_experiments(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        owner_id: UUID = ...,
        limit: int = 100,
    ) -> list[ExperimentRow]: ...

    async def set_status(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
        status: str,
        owner_id: UUID = ...,
    ) -> ExperimentRow | None: ...

    async def insert_result(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
        kind: str,
        direction: str | None,
        diff: float | None,
        effect_size: float | None,
        p_value: float | None,
        inference: str | None,
        summary: str | None,
        structured_data: dict[str, Any],
        owner_id: UUID = ...,
        workspace_id: UUID = ...,
    ) -> ExperimentResultRow: ...

    async def latest_results_by_kind(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
    ) -> dict[str, ExperimentResultRow]: ...


@runtime_checkable
class SyncReceiptRepository(Protocol):
    """Operator-facing HealthSave sync receipt reads."""

    async def latest_sync_run(self, session: Any) -> dict[str, Any]: ...

    async def sync_run(self, session: Any, sync_run_id: str) -> dict[str, Any]: ...

    async def sync_coverage(self, session: Any) -> dict[str, Any]: ...

    async def sync_anomalies(
        self,
        session: Any,
        lookback_minutes: int = 15,
    ) -> dict[str, Any]: ...
