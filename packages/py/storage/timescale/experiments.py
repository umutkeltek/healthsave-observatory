"""TimescaleDB implementation of :class:`storage.ports.ExperimentRepository`.

Persistence for the n-of-1 experiment engine (migration 013): the experiment
*definitions* (lever, outcome, ABAB design, schedule, status) plus the analysis
*results* the runtime computes against them. The pure statistics live in
``analysis.statistical.experiments`` and the orchestration in
``analysis.experiments`` — this module only reads and writes rows.

Like every storage module it is stateless (the caller owns the
session/transaction) and returns frozen dataclasses, never ORM rows. Two
surfaces, like ``briefings.py`` / ``agents.py``:
- :class:`TimescaleExperimentRepository` — class form for injection.
- Module-level functions delegating to ``default_repository``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ExperimentRow:
    """One row from ``experiments`` — an n-of-1 experiment definition."""

    id: UUID
    lever_metric_id: str
    outcome_metric_id: str
    design: str
    block_days: int
    start_date: date
    hypothesis: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExperimentResultRow:
    """One row from ``experiment_results`` — a computed analysis.

    ``structured_data`` is the parsed JSON payload (full means / n / block count
    / adherence / caveat). The promoted columns are the ones the dashboard sorts
    and badges on.
    """

    id: UUID
    experiment_id: UUID
    kind: str  # "retrospective" | "controlled"
    computed_at: datetime
    direction: str | None
    diff: float | None
    effect_size: float | None
    p_value: float | None
    inference: str | None
    summary: str | None
    structured_data: dict[str, Any]


# Columns shared by every SELECT/RETURNING on each table, so the row mappers see
# a stable shape.
_EXPERIMENT_COLS = (
    "id, lever_metric_id, outcome_metric_id, design, block_days, "
    "start_date, hypothesis, status, created_at, updated_at"
)
_RESULT_COLS = (
    "id, experiment_id, kind, computed_at, direction, diff, effect_size, "
    "p_value, inference, summary, structured_data"
)


def _parse_structured_data(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _experiment_from_row(row: Any) -> ExperimentRow:
    return ExperimentRow(
        id=row.id,
        lever_metric_id=row.lever_metric_id,
        outcome_metric_id=row.outcome_metric_id,
        design=row.design,
        block_days=row.block_days,
        start_date=row.start_date,
        hypothesis=row.hypothesis,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _result_from_row(row: Any) -> ExperimentResultRow:
    return ExperimentResultRow(
        id=row.id,
        experiment_id=row.experiment_id,
        kind=row.kind,
        computed_at=row.computed_at,
        direction=row.direction,
        diff=row.diff,
        effect_size=row.effect_size,
        p_value=row.p_value,
        inference=row.inference,
        summary=row.summary,
        structured_data=_parse_structured_data(row.structured_data),
    )


class TimescaleExperimentRepository:
    """TimescaleDB-backed :class:`storage.ports.ExperimentRepository`.

    Stateless. Every method takes the session as an argument; the caller composes
    the transaction boundary and commits.
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
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> ExperimentRow:
        sql = text(
            f"""
            INSERT INTO experiments (
                lever_metric_id, outcome_metric_id, design, block_days,
                start_date, hypothesis, owner_id, workspace_id
            )
            VALUES (
                :lever_metric_id, :outcome_metric_id, :design, :block_days,
                :start_date, :hypothesis, :owner_id, :workspace_id
            )
            RETURNING {_EXPERIMENT_COLS}
            """
        )
        result = await session.execute(
            sql,
            {
                "lever_metric_id": lever_metric_id,
                "outcome_metric_id": outcome_metric_id,
                "design": design,
                "block_days": block_days,
                "start_date": start_date,
                "hypothesis": hypothesis,
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return _experiment_from_row(result.first())

    async def get_experiment(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> ExperimentRow | None:
        sql = text(
            f"""
            SELECT {_EXPERIMENT_COLS}
              FROM experiments
             WHERE id = :experiment_id AND owner_id = :owner_id
            """
        )
        result = await session.execute(
            sql, {"experiment_id": str(experiment_id), "owner_id": str(owner_id)}
        )
        row = result.first()
        return _experiment_from_row(row) if row is not None else None

    async def list_experiments(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
        limit: int = 100,
    ) -> list[ExperimentRow]:
        where = ["owner_id = :owner_id"]
        params: dict[str, Any] = {"owner_id": str(owner_id), "limit": limit}
        if status is not None:
            where.append("status = :status")
            params["status"] = status
        sql = text(
            f"""
            SELECT {_EXPERIMENT_COLS}
              FROM experiments
             WHERE {" AND ".join(where)}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        )
        result = await session.execute(sql, params)
        return [_experiment_from_row(row) for row in result.fetchall()]

    async def set_status(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
        status: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> ExperimentRow | None:
        """Update an experiment's status (bumping ``updated_at``).

        Returns the updated row, or ``None`` when no experiment with that id
        exists for the owner — lets the route map a missing experiment to 404
        without a second query.
        """
        sql = text(
            f"""
            UPDATE experiments
               SET status = :status, updated_at = now()
             WHERE id = :experiment_id AND owner_id = :owner_id
            RETURNING {_EXPERIMENT_COLS}
            """
        )
        result = await session.execute(
            sql,
            {"experiment_id": str(experiment_id), "status": status, "owner_id": str(owner_id)},
        )
        row = result.first()
        return _experiment_from_row(row) if row is not None else None

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
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> ExperimentResultRow:
        sql = text(
            f"""
            INSERT INTO experiment_results (
                experiment_id, kind, direction, diff, effect_size, p_value,
                inference, summary, structured_data, owner_id, workspace_id
            )
            VALUES (
                :experiment_id, :kind, :direction, :diff, :effect_size, :p_value,
                :inference, :summary, CAST(:structured_data AS JSONB),
                :owner_id, :workspace_id
            )
            RETURNING {_RESULT_COLS}
            """
        )
        result = await session.execute(
            sql,
            {
                "experiment_id": str(experiment_id),
                "kind": kind,
                "direction": direction,
                "diff": diff,
                "effect_size": effect_size,
                "p_value": p_value,
                "inference": inference,
                "summary": summary,
                "structured_data": json.dumps(structured_data),
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
            },
        )
        return _result_from_row(result.first())

    async def latest_results_by_kind(
        self,
        session: AsyncSession,
        *,
        experiment_id: UUID,
    ) -> dict[str, ExperimentResultRow]:
        """Most recent result per ``kind`` (retrospective / controlled)."""
        sql = text(
            f"""
            SELECT DISTINCT ON (kind) {_RESULT_COLS}
              FROM experiment_results
             WHERE experiment_id = :experiment_id
             ORDER BY kind, computed_at DESC
            """
        )
        result = await session.execute(sql, {"experiment_id": str(experiment_id)})
        return {row.kind: _result_from_row(row) for row in result.fetchall()}


# Default instance for callers that haven't migrated to injection.
default_repository = TimescaleExperimentRepository()


# ──────────────────────────────────────────────────────────────────────
# Module-level convenience wrappers — delegate to ``default_repository``.
# ──────────────────────────────────────────────────────────────────────


async def create_experiment(
    session: AsyncSession,
    *,
    lever_metric_id: str,
    outcome_metric_id: str,
    design: str,
    block_days: int,
    start_date: date,
    hypothesis: str | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> ExperimentRow:
    return await default_repository.create_experiment(
        session,
        lever_metric_id=lever_metric_id,
        outcome_metric_id=outcome_metric_id,
        design=design,
        block_days=block_days,
        start_date=start_date,
        hypothesis=hypothesis,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def get_experiment(
    session: AsyncSession,
    *,
    experiment_id: UUID,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> ExperimentRow | None:
    return await default_repository.get_experiment(
        session, experiment_id=experiment_id, owner_id=owner_id
    )


async def list_experiments(
    session: AsyncSession,
    *,
    status: str | None = None,
    owner_id: UUID = DEFAULT_OWNER_ID,
    limit: int = 100,
) -> list[ExperimentRow]:
    return await default_repository.list_experiments(
        session, status=status, owner_id=owner_id, limit=limit
    )


async def set_status(
    session: AsyncSession,
    *,
    experiment_id: UUID,
    status: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> ExperimentRow | None:
    return await default_repository.set_status(
        session, experiment_id=experiment_id, status=status, owner_id=owner_id
    )


async def insert_result(
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
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> ExperimentResultRow:
    return await default_repository.insert_result(
        session,
        experiment_id=experiment_id,
        kind=kind,
        direction=direction,
        diff=diff,
        effect_size=effect_size,
        p_value=p_value,
        inference=inference,
        summary=summary,
        structured_data=structured_data,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


async def latest_results_by_kind(
    session: AsyncSession,
    *,
    experiment_id: UUID,
) -> dict[str, ExperimentResultRow]:
    return await default_repository.latest_results_by_kind(session, experiment_id=experiment_id)
