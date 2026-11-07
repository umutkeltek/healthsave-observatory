"""Timescale reads behind the Year in Health view (``GET /api/v2/year/{year}``).

All SQL for the view lives here (storage zone). Two reads, both owner-scoped:

* which metrics and which device streams have at least one active observation
  on each analytical day of the window (one row per metric, stream, scope and
  day — never per observation);
* each stream's all-time first and last OBSERVATION time. The registry's own
  ``first_seen_at`` / ``last_seen_at`` are ingest times (a backfill moves
  them), so device changes are read from the observations instead. The
  per-stream lookups ride the partial index from migration 016.

The reading of these rows (months, gaps, device changes) is pure and lives in
``analysis.statistical.year``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from contracts._base import DEFAULT_WORKSPACE_ID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PRESENCE_SQL = text(
    """
    SELECT metric_id,
           stream_id,
           aggregation_scope,
           date_trunc(
               'day',
               (interval_start AT TIME ZONE :time_zone)
               - make_interval(mins => :day_boundary_minutes)
           )::date AS day,
           count(*) AS observation_count
    FROM canonical_observations
    WHERE owner_id = :owner_id
      AND workspace_id = :workspace_id
      AND status = 'active'
      AND interval_start >= :start
      AND interval_start < :end
    GROUP BY metric_id, stream_id, aggregation_scope, day
    ORDER BY day, metric_id
    """
)

_STREAM_BOUNDS_SQL = text(
    """
    SELECT s.id AS stream_id,
           s.source_plugin_id,
           s.origin_key,
           s.device_label,
           (SELECT o.interval_start
              FROM canonical_observations o
             WHERE o.owner_id = s.owner_id
               AND o.workspace_id = :workspace_id
               AND o.stream_id = s.id
               AND o.status = 'active'
             ORDER BY o.interval_start ASC
             LIMIT 1) AS first_at,
           (SELECT o.interval_start
              FROM canonical_observations o
             WHERE o.owner_id = s.owner_id
               AND o.workspace_id = :workspace_id
               AND o.stream_id = s.id
               AND o.status = 'active'
             ORDER BY o.interval_start DESC
             LIMIT 1) AS last_at
    FROM source_device_streams s
    WHERE s.owner_id = :owner_id
    ORDER BY s.id
    """
)


@dataclass(frozen=True, slots=True)
class PresenceRow:
    metric_id: str
    stream_id: UUID | None
    aggregation_scope: str
    day: date
    observation_count: int


@dataclass(frozen=True, slots=True)
class StreamBoundsRow:
    stream_id: UUID
    source_plugin_id: str
    origin_key: str
    device_label: str | None
    first_at: datetime | None
    last_at: datetime | None


class TimescaleYearRepository:
    async def day_presence(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        start: datetime,
        end: datetime,
        time_zone: str,
        day_boundary_minutes: int,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> list[PresenceRow]:
        """Per metric, stream, scope and analytical day in ``[start, end)``."""
        result = await session.execute(
            _PRESENCE_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "start": start,
                "end": end,
                "time_zone": time_zone,
                "day_boundary_minutes": day_boundary_minutes,
            },
        )
        return [
            PresenceRow(
                metric_id=row.metric_id,
                stream_id=row.stream_id,
                aggregation_scope=row.aggregation_scope,
                day=row.day,
                observation_count=int(row.observation_count or 0),
            )
            for row in result
        ]

    async def stream_bounds(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> list[StreamBoundsRow]:
        """Every stream of the owner with its first and last observation time."""
        result = await session.execute(
            _STREAM_BOUNDS_SQL,
            {"owner_id": str(owner_id), "workspace_id": str(workspace_id)},
        )
        return [
            StreamBoundsRow(
                stream_id=row.stream_id,
                source_plugin_id=row.source_plugin_id,
                origin_key=row.origin_key,
                device_label=row.device_label,
                first_at=row.first_at,
                last_at=row.last_at,
            )
            for row in result
        ]


default_repository = TimescaleYearRepository()
