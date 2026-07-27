"""Person-local Observatory settings for reproducible calendar analysis."""

from __future__ import annotations

from typing import Annotated
from zoneinfo import available_timezones

from contracts._base import V2Model
from contracts.analytical_time import (
    DEFAULT_DAY_BOUNDARY_MINUTES,
    DEFAULT_TIME_ZONE,
    MAX_DAY_BOUNDARY_MINUTES,
    AnalyticalTime,
)
from fastapi import APIRouter, Depends
from pydantic import Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale.observatory_settings import default_repository

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2/settings", dependencies=[Depends(verify_api_key)])

TimeZoneName = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class AnalyticalTimeView(V2Model):
    time_zone: str
    day_boundary_minutes: int
    day_boundary: str
    revision: int
    sleep_day_assignment: str = "wake_time"


class UpdateAnalyticalTimeRequest(V2Model):
    time_zone: TimeZoneName
    day_boundary_minutes: int = Field(ge=0, le=MAX_DAY_BOUNDARY_MINUTES)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        # Constructing AnalyticalTime is the canonical validation path. The
        # available-timezones check gives Pydantic a stable field-local error.
        if value not in available_timezones():
            raise ValueError("must be a known IANA time zone")
        AnalyticalTime(value, DEFAULT_DAY_BOUNDARY_MINUTES)
        return value


def _view(time_zone: str, day_boundary_minutes: int, revision: int) -> AnalyticalTimeView:
    config = AnalyticalTime(time_zone, day_boundary_minutes)
    return AnalyticalTimeView(
        time_zone=config.time_zone,
        day_boundary_minutes=config.day_boundary_minutes,
        day_boundary=config.boundary_label,
        revision=revision,
    )


@router.get("/analytical-time", response_model=AnalyticalTimeView)
async def get_analytical_time(
    session: AsyncSession = Depends(get_session),
) -> AnalyticalTimeView:
    settings = await default_repository.get(session)
    if settings is None:
        return _view(DEFAULT_TIME_ZONE, DEFAULT_DAY_BOUNDARY_MINUTES, 0)
    return _view(settings.time_zone, settings.day_boundary_minutes, settings.revision)


@router.put("/analytical-time", response_model=AnalyticalTimeView)
async def update_analytical_time(
    body: UpdateAnalyticalTimeRequest,
    session: AsyncSession = Depends(get_session),
) -> AnalyticalTimeView:
    settings = await default_repository.update(
        session,
        time_zone=body.time_zone,
        day_boundary_minutes=body.day_boundary_minutes,
    )
    await session.commit()
    return _view(settings.time_zone, settings.day_boundary_minutes, settings.revision)
