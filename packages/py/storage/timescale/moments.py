"""Timescale persistence for personal-context moments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MOMENT_KINDS = frozenset(
    {
        "illness",
        "alcohol",
        "late_meal",
        "travel",
        "medication_change",
        "supplement_change",
        "hard_training",
        "stress",
        "caffeine",
        "injury",
        "menstrual",
        "custom",
    }
)
GRADES = frozenset({"mild", "moderate", "severe"})
_MOMENT_COLS = "id, owner_id, kind, grade, title, note, start_at, end_at, created_at, updated_at"
_DEFAULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class Moment:
    id: int
    owner_id: UUID
    kind: str
    grade: str | None
    title: str
    note: str | None
    start_at: datetime
    end_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


def _moment_from_row(row) -> Moment:
    return Moment(
        id=row.id,
        owner_id=row.owner_id,
        kind=row.kind,
        grade=row.grade,
        title=row.title,
        note=row.note,
        start_at=row.start_at,
        end_at=row.end_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TimescaleMomentsRepository:
    async def list(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        limit: int = _DEFAULT_LIMIT,
        before: datetime | None = None,
    ) -> list[Moment]:
        result = await session.execute(
            text(
                f"""
                SELECT {_MOMENT_COLS}
                  FROM moments
                 WHERE owner_id = :owner_id
                   AND (start_at < :before OR :before IS NULL)
                 ORDER BY start_at DESC
                 LIMIT :limit
                """
            ),
            {"owner_id": str(owner_id), "before": before, "limit": limit},
        )
        return [_moment_from_row(row) for row in result.fetchall()]

    async def get(
        self,
        session: AsyncSession,
        *,
        id: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Moment | None:
        result = await session.execute(
            text(
                f"""
                SELECT {_MOMENT_COLS}
                  FROM moments
                 WHERE id = :id AND owner_id = :owner_id
                """
            ),
            {"id": id, "owner_id": str(owner_id)},
        )
        row = result.first()
        return _moment_from_row(row) if row is not None else None

    async def create(
        self,
        session: AsyncSession,
        *,
        kind: str,
        title: str,
        start_at: datetime,
        end_at: datetime | None = None,
        grade: str | None = None,
        note: str | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Moment:
        result = await session.execute(
            text(
                f"""
                INSERT INTO moments (owner_id, kind, grade, title, note, start_at, end_at)
                VALUES (:owner_id, :kind, :grade, :title, :note, :start_at, :end_at)
                RETURNING {_MOMENT_COLS}
                """
            ),
            {
                "owner_id": str(owner_id),
                "kind": kind,
                "grade": grade,
                "title": title,
                "note": note,
                "start_at": start_at,
                "end_at": end_at,
            },
        )
        return _moment_from_row(result.first())

    async def update(
        self,
        session: AsyncSession,
        *,
        id: int,
        kind: str,
        title: str,
        start_at: datetime,
        end_at: datetime | None = None,
        grade: str | None = None,
        note: str | None = None,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> Moment | None:
        result = await session.execute(
            text(
                f"""
                UPDATE moments
                   SET kind      = :kind,
                       grade     = :grade,
                       title     = :title,
                       note      = :note,
                       start_at  = :start_at,
                       end_at    = :end_at,
                       updated_at = NOW()
                 WHERE id = :id AND owner_id = :owner_id
                RETURNING {_MOMENT_COLS}
                """
            ),
            {
                "id": id,
                "owner_id": str(owner_id),
                "kind": kind,
                "grade": grade,
                "title": title,
                "note": note,
                "start_at": start_at,
                "end_at": end_at,
            },
        )
        row = result.first()
        return _moment_from_row(row) if row is not None else None

    async def delete(
        self,
        session: AsyncSession,
        *,
        id: int,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> bool:
        result = await session.execute(
            text(
                """
                DELETE FROM moments
                 WHERE id = :id AND owner_id = :owner_id
                """
            ),
            {"id": id, "owner_id": str(owner_id)},
        )
        return result.rowcount > 0


default_repository = TimescaleMomentsRepository()
__all__ = [
    "MOMENT_KINDS",
    "GRADES",
    "Moment",
    "TimescaleMomentsRepository",
    "default_repository",
]
