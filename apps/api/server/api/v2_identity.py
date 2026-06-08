"""v2 Source / Device / Stream read API (R2 Track A).

Typed, contract-first read surface for the identity model — the half that was
missing. These are keyed (they expose device/stream metadata). The SQL lives in
``storage.timescale.registry``; routes only shape the response.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import registry

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])


class SourceView(BaseModel):
    id: UUID
    plugin_id: str
    display_name: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime


class StreamView(BaseModel):
    id: UUID
    source_plugin_id: str
    origin_key: str
    device_label: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime


class DeviceView(BaseModel):
    device_label: str | None = None
    stream_count: int
    first_seen_at: datetime
    last_seen_at: datetime


class SourcesResponse(BaseModel):
    count: int
    sources: list[SourceView]


class StreamsResponse(BaseModel):
    count: int
    streams: list[StreamView]


class DevicesResponse(BaseModel):
    count: int
    devices: list[DeviceView]


@router.get("/sources", response_model=SourcesResponse)
async def list_sources(session: AsyncSession = Depends(get_session)) -> SourcesResponse:
    rows = await registry.list_sources(session, DEFAULT_OWNER_ID)
    return SourcesResponse(count=len(rows), sources=rows)


@router.get("/devices", response_model=DevicesResponse)
async def list_devices(session: AsyncSession = Depends(get_session)) -> DevicesResponse:
    rows = await registry.list_devices(session, DEFAULT_OWNER_ID)
    return DevicesResponse(count=len(rows), devices=rows)


@router.get("/streams", response_model=StreamsResponse)
async def list_streams(session: AsyncSession = Depends(get_session)) -> StreamsResponse:
    rows = await registry.list_streams(session, DEFAULT_OWNER_ID)
    return StreamsResponse(count=len(rows), streams=rows)


@router.get("/streams/{stream_id}", response_model=StreamView)
async def get_stream(stream_id: UUID, session: AsyncSession = Depends(get_session)) -> StreamView:
    row = await registry.get_stream(session, DEFAULT_OWNER_ID, stream_id)
    if row is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return StreamView(**row)
