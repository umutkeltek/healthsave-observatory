"""Personal-context moments — the life events that explain or confound changes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from contracts._base import V2Model
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale.moments import GRADES, MOMENT_KINDS, default_repository

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2/moments", dependencies=[Depends(verify_api_key)])

MomentKind = Annotated[str, StringConstraints(min_length=1, max_length=32)]
MomentGrade = Annotated[str, StringConstraints(min_length=1, max_length=12)] | None


class MomentView(V2Model):
    id: int
    kind: str
    grade: str | None
    title: str
    note: str | None
    start_at: datetime
    end_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class MomentListResponse(V2Model):
    moments: list[MomentView]
    count: int


class CreateMomentRequest(V2Model):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime | None = None
    grade: MomentGrade = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in MOMENT_KINDS:
            raise ValueError(f"must be one of: {', '.join(sorted(MOMENT_KINDS))}")
        return value

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, value: str | None) -> str | None:
        if value is not None and value not in GRADES:
            raise ValueError(f"grade must be one of: {', '.join(sorted(GRADES))}")
        return value


class UpdateMomentRequest(CreateMomentRequest):
    pass


def _view(moment) -> MomentView:
    return MomentView(
        id=moment.id,
        kind=moment.kind,
        grade=moment.grade,
        title=moment.title,
        note=moment.note,
        start_at=moment.start_at,
        end_at=moment.end_at,
        created_at=moment.created_at,
        updated_at=moment.updated_at,
    )


@router.get("", response_model=MomentListResponse)
async def list_moments(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> MomentListResponse:
    moments = await default_repository.list(session, limit=limit)
    return MomentListResponse(
        moments=[_view(moment) for moment in moments],
        count=len(moments),
    )


@router.post("", response_model=MomentView, status_code=201)
async def create_moment(
    body: CreateMomentRequest,
    session: AsyncSession = Depends(get_session),
) -> MomentView:
    moment = await default_repository.create(
        session,
        kind=body.kind,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        grade=body.grade,
        note=body.note,
    )
    await session.commit()
    return _view(moment)


@router.put("/{moment_id}", response_model=MomentView)
async def update_moment(
    moment_id: int,
    body: UpdateMomentRequest,
    session: AsyncSession = Depends(get_session),
) -> MomentView:
    moment = await default_repository.update(
        session,
        id=moment_id,
        kind=body.kind,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        grade=body.grade,
        note=body.note,
    )
    if moment is None:
        raise HTTPException(status_code=404, detail="moment not found")
    await session.commit()
    return _view(moment)


@router.delete("/{moment_id}", status_code=200, response_model=dict)
async def delete_moment(
    moment_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    deleted = await default_repository.delete(session, id=moment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="moment not found")
    await session.commit()
    return {"ok": True}
