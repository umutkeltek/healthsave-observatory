"""Timescale persistence for Observatory person-local analytical settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contracts._base import DEFAULT_OWNER_ID


@dataclass(frozen=True, slots=True)
class ObservatorySettings:
    time_zone: str
    day_boundary_minutes: int
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TimescaleObservatorySettingsRepository:
    async def get(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> ObservatorySettings | None:
        result = await session.execute(
            text(
                """
                SELECT time_zone, day_boundary_minutes, revision, created_at, updated_at
                FROM observatory_settings
                WHERE owner_id = :owner_id
                """
            ),
            {"owner_id": str(owner_id)},
        )
        row = result.first()
        if row is None:
            return None
        return ObservatorySettings(
            time_zone=row.time_zone,
            day_boundary_minutes=row.day_boundary_minutes,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        time_zone: str,
        day_boundary_minutes: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> ObservatorySettings:
        result = await session.execute(
            text(
                """
                INSERT INTO observatory_settings (
                    owner_id, time_zone, day_boundary_minutes, revision
                ) VALUES (
                    :owner_id, :time_zone, :day_boundary_minutes, 1
                )
                ON CONFLICT (owner_id) DO UPDATE
                SET time_zone = EXCLUDED.time_zone,
                    day_boundary_minutes = EXCLUDED.day_boundary_minutes,
                    revision = observatory_settings.revision + 1,
                    updated_at = NOW()
                RETURNING time_zone, day_boundary_minutes, revision, created_at, updated_at
                """
            ),
            {
                "owner_id": str(owner_id),
                "time_zone": time_zone,
                "day_boundary_minutes": day_boundary_minutes,
            },
        )
        row = result.first()
        return ObservatorySettings(
            time_zone=row.time_zone,
            day_boundary_minutes=row.day_boundary_minutes,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


default_repository = TimescaleObservatorySettingsRepository()
