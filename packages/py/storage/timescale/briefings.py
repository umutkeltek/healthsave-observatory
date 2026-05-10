"""TimescaleDB implementation of :class:`storage.ports.BriefingRepository`.

Read-side data access for the analysis surface that ``/api/insights/*``
serves. The route handlers stay responsible for parameter validation
(reject malformed ``period``, restrict severity values, etc.) — this
module assumes inputs are already valid and just runs the SQL.

Two surfaces, like ``runs.py``:
- :class:`TimescaleBriefingRepository` — class form for injection.
- Module-level functions delegating to ``default_repository`` — for
  v1.x callers that want the simpler call shape.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class NarrativeRow:
    """One row from ``analysis_insights``. Wire-mapped by the route."""

    insight_type: str
    narrative: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FindingRow:
    """One row from ``analysis_findings``.

    ``structured_data`` is the parsed JSON payload — the route handler
    pulls out type-specific fields (magnitude/direction for anomalies,
    slope/p_value/period_days for trends).
    """

    id: int
    metric: str | None
    severity: str | None
    structured_data: dict[str, Any]
    created_at: datetime


def _parse_structured_data(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


class TimescaleBriefingRepository:
    """TimescaleDB-backed :class:`storage.ports.BriefingRepository`.

    Stateless. Every method takes the session as an argument; the
    caller composes the transaction boundary.
    """

    async def latest_narratives_by_type(
        self,
        session: AsyncSession,
        *,
        insight_types: Iterable[str] = ("daily_briefing", "weekly_summary"),
    ) -> dict[str, NarrativeRow]:
        """Most recent narrative per ``insight_type`` (DISTINCT ON pattern)."""
        type_list = sorted(set(insight_types))
        if not type_list:
            return {}

        # Build a parameterised IN clause so the query plan stays cached.
        placeholders = []
        params: dict[str, Any] = {}
        for index, t in enumerate(type_list):
            name = f"t{index}"
            placeholders.append(f":{name}")
            params[name] = t

        sql = text(
            f"""
            SELECT DISTINCT ON (insight_type)
                insight_type, narrative, created_at
            FROM analysis_insights
            WHERE insight_type IN ({", ".join(placeholders)})
            ORDER BY insight_type, created_at DESC
            """
        )
        rows = (await session.execute(sql, params)).fetchall()
        return {
            row.insight_type: NarrativeRow(
                insight_type=row.insight_type,
                narrative=row.narrative,
                created_at=row.created_at,
            )
            for row in rows
        }

    async def fetch_anomalies(
        self,
        session: AsyncSession,
        *,
        since: datetime | None = None,
        severities: Iterable[str] | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        """Anomaly findings, newest first.

        Reads ``analysis_findings`` where ``finding_type='anomaly'``.
        ``severities`` is treated as a fully-validated allowlist — the
        route handler rejects unknown values *before* calling this.
        """
        where_clauses = ["finding_type = 'anomaly'"]
        params: dict[str, Any] = {"limit": limit}

        if since is not None:
            where_clauses.append("created_at >= :since")
            params["since"] = since

        if severities is not None:
            severity_list = sorted(set(severities))
            if severity_list:
                placeholders = []
                for index, value in enumerate(severity_list):
                    name = f"severity_{index}"
                    placeholders.append(f":{name}")
                    params[name] = value
                where_clauses.append(f"severity IN ({', '.join(placeholders)})")

        sql = text(
            f"""
            SELECT id, metric, severity, structured_data, created_at
              FROM analysis_findings
             WHERE {" AND ".join(where_clauses)}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).fetchall()
        return [
            FindingRow(
                id=row.id,
                metric=row.metric,
                # Tests substitute SimpleNamespace rows that may omit
                # the severity column for finding_type='trend' (where
                # severity is always NULL); getattr keeps both shapes
                # working without requiring fixture churn.
                severity=getattr(row, "severity", None),
                structured_data=_parse_structured_data(row.structured_data),
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def fetch_trends(
        self,
        session: AsyncSession,
        *,
        period_days: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        """Trend findings, newest first.

        ``period_days`` is matched against the JSONB
        ``structured_data->>'period_days'`` so the API can filter by
        ``?period=30d`` (route extracts the leading digits and passes
        them as a string). Pre-validation lives in the route.
        """
        where_clauses = ["finding_type = 'trend'"]
        params: dict[str, Any] = {"limit": limit}

        if period_days is not None:
            params["period_days"] = period_days
            where_clauses.append("structured_data->>'period_days' = :period_days")

        sql = text(
            f"""
            SELECT id, metric, severity, structured_data, created_at
              FROM analysis_findings
             WHERE {" AND ".join(where_clauses)}
             ORDER BY created_at DESC
             LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).fetchall()
        return [
            FindingRow(
                id=row.id,
                metric=row.metric,
                # Tests substitute SimpleNamespace rows that may omit
                # the severity column for finding_type='trend' (where
                # severity is always NULL); getattr keeps both shapes
                # working without requiring fixture churn.
                severity=getattr(row, "severity", None),
                structured_data=_parse_structured_data(row.structured_data),
                created_at=row.created_at,
            )
            for row in rows
        ]


# Default instance for v1.x callers that haven't migrated to injection.
default_repository = TimescaleBriefingRepository()


# Module-level convenience wrappers — same signatures as the class
# methods, delegating to ``default_repository``.


async def latest_narratives_by_type(
    session: AsyncSession,
    *,
    insight_types: Iterable[str] = ("daily_briefing", "weekly_summary"),
) -> dict[str, NarrativeRow]:
    return await default_repository.latest_narratives_by_type(session, insight_types=insight_types)


async def fetch_anomalies(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    severities: Iterable[str] | None = None,
    limit: int = 200,
) -> list[FindingRow]:
    return await default_repository.fetch_anomalies(
        session, since=since, severities=severities, limit=limit
    )


async def fetch_trends(
    session: AsyncSession,
    *,
    period_days: str | None = None,
    limit: int = 200,
) -> list[FindingRow]:
    return await default_repository.fetch_trends(session, period_days=period_days, limit=limit)
