"""TimescaleDB implementation of the AgentRun ledger repository.

Phase 7-B ships the storage-zone home for every read + write against
the six Phase 7-A tables (``agent_runs``, ``agent_events``,
``action_proposals``, ``action_decisions``, ``action_executions``,
``agent_artifacts``). The Phase 7-C supervisor and the Phase 7-E
``/api/v2/agents/*`` routes are the consumers; this module is the
only place that knows the SQL.

Mirrors the pattern from :mod:`storage.timescale.runs` and
:mod:`storage.timescale.briefings`:

  * :class:`TimescaleAgentRepository` — the proper class form, inject
    into consumers that want swappable storage (the supervisor will).
  * :data:`default_repository` — module-level singleton for tests
    and v1.x-style direct calls.
  * Module-level convenience functions — thin wrappers over
    ``default_repository`` for code that just wants ``await
    propose_action(session, ...)`` without injection.

Caller owns the transaction. Methods take ``AsyncSession`` and never
``await session.commit()`` themselves — the supervisor composes
``start_run + record_event + ...`` inside one transaction and commits
once, so the ledger row write and its 'run_started' event row either
both land or both roll back.

Read projections are frozen dataclasses so callers never see
SQLAlchemy ``Row`` objects (the storage zone seal works both ways).
Phase 7-E maps these to the Pydantic V2Model shapes at the route
boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ──────────────────────────────────────────────────────────────────────
# Literal aliases — mirror packages/py/contracts/agents.py
# ──────────────────────────────────────────────────────────────────────

RunStatus = Literal["running", "completed", "failed", "cancelled"]
TriggerKind = Literal["cron", "ingest_event", "metric_threshold", "manual"]
ActionKind = Literal[
    "notify",
    "create_experiment",
    "create_briefing",
    "request_user_input",
    "tag_measurement",
]
Decision = Literal["approved", "rejected", "deferred"]
DecidedBy = Literal["user", "policy", "auto"]
ExecutionStatus = Literal["succeeded", "failed", "skipped"]
EventKind = Literal[
    "run_started",
    "run_completed",
    "run_failed",
    "observation",
    "proposal_created",
    "proposal_approved",
    "proposal_rejected",
    "execution_succeeded",
    "execution_failed",
    "artifact_created",
]
ArtifactKind = Literal[
    "narrative",
    "chart_spec",
    "experiment_plan",
    "intervention_proposal",
]


# ──────────────────────────────────────────────────────────────────────
# Read projections
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentRunRow:
    id: UUID
    plugin_id: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    trigger_kind: TriggerKind
    trigger_metadata: dict[str, Any]
    owner_id: UUID
    workspace_id: UUID


@dataclass(frozen=True, slots=True)
class ProposalRow:
    id: UUID
    run_id: UUID
    proposed_at: datetime
    action_kind: ActionKind
    payload: dict[str, Any]
    rationale: str
    capability: str
    idempotency_key: str | None
    owner_id: UUID
    workspace_id: UUID


# Default sentinel mirrors the per-table DEFAULT in 006_agent_runtime.sql
# and matches the v1+v2 single-user owner UUID elsewhere in the codebase.
DEFAULT_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class TimescaleAgentRepository:
    """TimescaleDB-backed AgentRun ledger repository.

    Stateless — every method takes the session as an argument. Construct
    once at module import; share the instance across consumers.
    """

    # ── Runs ──────────────────────────────────────────────────────────

    async def start_run(
        self,
        session: AsyncSession,
        *,
        plugin_id: str,
        trigger_kind: TriggerKind,
        trigger_metadata: dict[str, Any] | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID:
        sql = text(
            """
            INSERT INTO agent_runs (
                plugin_id, status, started_at,
                trigger_kind, trigger_metadata,
                owner_id, workspace_id
            )
            VALUES (
                :plugin_id, 'running', now(),
                :trigger_kind, :trigger_metadata,
                :owner_id, :workspace_id
            )
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "plugin_id": plugin_id,
                "trigger_kind": trigger_kind,
                "trigger_metadata": json.dumps(trigger_metadata or {}),
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return result.first().id

    async def mark_run_terminal(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> None:
        if status == "running":
            raise ValueError("mark_run_terminal requires a terminal status")
        sql = text(
            """
            UPDATE agent_runs
               SET status = :status,
                   ended_at = now()
             WHERE id = :run_id
            """
        )
        await session.execute(sql, {"run_id": str(run_id), "status": status})

    # ── Proposals ─────────────────────────────────────────────────────

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
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID | None:
        """Insert a proposal.

        When ``idempotency_key`` is set and the partial unique index on
        ``action_proposals.idempotency_key`` already holds a row with
        the same key, the INSERT is a no-op and this returns ``None``.
        Caller treats ``None`` as 'already proposed; do not re-emit
        downstream events'.

        When ``idempotency_key`` is ``None``, the INSERT always lands
        and the row id is returned.
        """
        sql = text(
            """
            INSERT INTO action_proposals (
                run_id, proposed_at, action_kind, payload,
                rationale, capability, idempotency_key,
                owner_id, workspace_id
            )
            VALUES (
                :run_id, now(), :action_kind, :payload,
                :rationale, :capability, :idempotency_key,
                :owner_id, :workspace_id
            )
            ON CONFLICT (idempotency_key)
                WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "run_id": str(run_id),
                "action_kind": action_kind,
                "payload": json.dumps(payload),
                "rationale": rationale,
                "capability": capability,
                "idempotency_key": idempotency_key,
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        row = result.first()
        return row.id if row is not None else None

    async def decide_action(
        self,
        session: AsyncSession,
        *,
        proposal_id: UUID,
        decision: Decision,
        decided_by: DecidedBy,
        rationale: str | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID:
        sql = text(
            """
            INSERT INTO action_decisions (
                proposal_id, decided_at, decision, decided_by,
                rationale, owner_id, workspace_id
            )
            VALUES (
                :proposal_id, now(), :decision, :decided_by,
                :rationale, :owner_id, :workspace_id
            )
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "proposal_id": str(proposal_id),
                "decision": decision,
                "decided_by": decided_by,
                "rationale": rationale,
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return result.first().id

    async def execute_action(
        self,
        session: AsyncSession,
        *,
        proposal_id: UUID,
        decision_id: UUID,
        status: ExecutionStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID:
        sql = text(
            """
            INSERT INTO action_executions (
                proposal_id, decision_id, executed_at,
                status, result, error,
                owner_id, workspace_id
            )
            VALUES (
                :proposal_id, :decision_id, now(),
                :status, :result, :error,
                :owner_id, :workspace_id
            )
            RETURNING id
            """
        )
        sql_result = await session.execute(
            sql,
            {
                "proposal_id": str(proposal_id),
                "decision_id": str(decision_id),
                "status": status,
                "result": json.dumps(result or {}),
                "error": error,
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return sql_result.first().id

    # ── Events ────────────────────────────────────────────────────────

    async def record_event(
        self,
        session: AsyncSession,
        *,
        run_id: UUID | None,
        kind: EventKind,
        payload: dict[str, Any] | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID:
        sql = text(
            """
            INSERT INTO agent_events (
                run_id, emitted_at, kind, payload,
                owner_id, workspace_id
            )
            VALUES (
                :run_id, now(), :kind, :payload,
                :owner_id, :workspace_id
            )
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "run_id": str(run_id) if run_id is not None else None,
                "kind": kind,
                "payload": json.dumps(payload or {}),
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return result.first().id

    # ── Artifacts ─────────────────────────────────────────────────────

    async def record_artifact(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        kind: ArtifactKind,
        payload: dict[str, Any],
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> UUID:
        sql = text(
            """
            INSERT INTO agent_artifacts (
                run_id, kind, payload, created_at,
                owner_id, workspace_id
            )
            VALUES (
                :run_id, :kind, :payload, now(),
                :owner_id, :workspace_id
            )
            RETURNING id
            """
        )
        result = await session.execute(
            sql,
            {
                "run_id": str(run_id),
                "kind": kind,
                "payload": json.dumps(payload),
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return result.first().id

    # ── Reads ─────────────────────────────────────────────────────────

    async def fetch_recent_proposals(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        limit: int = 50,
        undecided_only: bool = False,
    ) -> list[ProposalRow]:
        """Recent proposals for the dashboard's approval queue.

        ``undecided_only=True`` filters to proposals that do not yet
        have a corresponding row in ``action_decisions`` — the
        actionable list for the Phase 7-E /decide route.
        """
        if undecided_only:
            sql = text(
                """
                SELECT
                    p.id, p.run_id, p.proposed_at, p.action_kind,
                    p.payload, p.rationale, p.capability,
                    p.idempotency_key, p.owner_id, p.workspace_id
                FROM action_proposals p
                LEFT JOIN action_decisions d ON d.proposal_id = p.id
                WHERE p.owner_id = :owner_id
                  AND d.id IS NULL
                ORDER BY p.proposed_at DESC
                LIMIT :limit
                """
            )
        else:
            sql = text(
                """
                SELECT
                    id, run_id, proposed_at, action_kind,
                    payload, rationale, capability,
                    idempotency_key, owner_id, workspace_id
                FROM action_proposals
                WHERE owner_id = :owner_id
                ORDER BY proposed_at DESC
                LIMIT :limit
                """
            )
        result = await session.execute(sql, {"owner_id": str(owner_id), "limit": limit})
        return [
            ProposalRow(
                id=row.id,
                run_id=row.run_id,
                proposed_at=row.proposed_at,
                action_kind=row.action_kind,
                payload=row.payload if isinstance(row.payload, dict) else json.loads(row.payload),
                rationale=row.rationale,
                capability=row.capability,
                idempotency_key=row.idempotency_key,
                owner_id=row.owner_id,
                workspace_id=row.workspace_id,
            )
            for row in result.fetchall()
        ]


# Module-level default — production wiring would inject its own, but
# tests + bootstrapping use this singleton.
default_repository = TimescaleAgentRepository()


# ──────────────────────────────────────────────────────────────────────
# Module-level convenience functions — delegate to default_repository
# ──────────────────────────────────────────────────────────────────────


async def start_run(
    session: AsyncSession,
    *,
    plugin_id: str,
    trigger_kind: TriggerKind,
    trigger_metadata: dict[str, Any] | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID:
    return await default_repository.start_run(
        session,
        plugin_id=plugin_id,
        trigger_kind=trigger_kind,
        trigger_metadata=trigger_metadata,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def mark_run_terminal(
    session: AsyncSession,
    *,
    run_id: UUID,
    status: RunStatus,
) -> None:
    await default_repository.mark_run_terminal(session, run_id=run_id, status=status)


async def propose_action(
    session: AsyncSession,
    *,
    run_id: UUID,
    action_kind: ActionKind,
    payload: dict[str, Any],
    rationale: str,
    capability: str,
    idempotency_key: str | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID | None:
    return await default_repository.propose_action(
        session,
        run_id=run_id,
        action_kind=action_kind,
        payload=payload,
        rationale=rationale,
        capability=capability,
        idempotency_key=idempotency_key,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def decide_action(
    session: AsyncSession,
    *,
    proposal_id: UUID,
    decision: Decision,
    decided_by: DecidedBy,
    rationale: str | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID:
    return await default_repository.decide_action(
        session,
        proposal_id=proposal_id,
        decision=decision,
        decided_by=decided_by,
        rationale=rationale,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def execute_action(
    session: AsyncSession,
    *,
    proposal_id: UUID,
    decision_id: UUID,
    status: ExecutionStatus,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID:
    return await default_repository.execute_action(
        session,
        proposal_id=proposal_id,
        decision_id=decision_id,
        status=status,
        result=result,
        error=error,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def record_event(
    session: AsyncSession,
    *,
    run_id: UUID | None,
    kind: EventKind,
    payload: dict[str, Any] | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID:
    return await default_repository.record_event(
        session,
        run_id=run_id,
        kind=kind,
        payload=payload,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def record_artifact(
    session: AsyncSession,
    *,
    run_id: UUID,
    kind: ArtifactKind,
    payload: dict[str, Any],
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> UUID:
    return await default_repository.record_artifact(
        session,
        run_id=run_id,
        kind=kind,
        payload=payload,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def fetch_recent_proposals(
    session: AsyncSession,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
    limit: int = 50,
    undecided_only: bool = False,
) -> list[ProposalRow]:
    return await default_repository.fetch_recent_proposals(
        session,
        owner_id=owner_id,
        limit=limit,
        undecided_only=undecided_only,
    )
