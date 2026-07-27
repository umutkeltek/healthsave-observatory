"""v2 Source / Device / Stream read API (R2 Track A).

Typed, contract-first read surface for the identity model — the half that was
missing. These are keyed (they expose device/stream metadata). The SQL lives in
``storage.timescale.registry``; routes only shape the response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from fastapi import APIRouter, Depends, HTTPException, Query
from normalization.fusion import DeviceLinkConfidence
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import registry
from storage.timescale.fusion import default_repository as fusion_repository

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


# Operator-facing write model for confirmed direct-vendor -> relayed-stream links.
class DeviceIdentityLinkCreate(BaseModel):
    direct_stream_id: UUID
    relayed_stream_id: UUID
    status: Literal["confirmed"] = "confirmed"
    confidence: Literal["medium", "strong"] = "strong"
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_distinct_streams(self) -> DeviceIdentityLinkCreate:
        if self.direct_stream_id == self.relayed_stream_id:
            raise ValueError("direct_stream_id and relayed_stream_id must differ")
        return self


class DeviceIdentityLinkResponse(BaseModel):
    direct_stream_id: UUID
    relayed_stream_id: UUID
    status: Literal["confirmed"]
    confidence: Literal["medium", "strong"]


class SessionFusionReconciliationResponse(BaseModel):
    matched_pairs: int
    assigned: int
    rejected: int


# `total` is additive: the full row count when paginating (count = page size).
# Unpaginated reads keep total == count, so existing consumers see no change
# in meaning.
class SourcesResponse(BaseModel):
    count: int
    total: int | None = None
    sources: list[SourceView]


class StreamsResponse(BaseModel):
    count: int
    total: int | None = None
    streams: list[StreamView]


class DevicesResponse(BaseModel):
    count: int
    total: int | None = None
    devices: list[DeviceView]


# Shared pagination params: limit=None keeps the original unbounded response.
# Annotated (not Query(default=…)) so direct test calls get real defaults and
# the FieldInfo isn't shared mutable state across signatures.
_Limit = Annotated[int | None, Query(ge=1, le=1000)]
_Offset = Annotated[int, Query(ge=0)]


@router.get("/sources", response_model=SourcesResponse)
async def list_sources(
    limit: _Limit = None,
    offset: _Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> SourcesResponse:
    rows = await registry.list_sources(session, DEFAULT_OWNER_ID, limit=limit, offset=offset)
    paged = limit is not None or offset > 0
    total = await registry.count_sources(session, DEFAULT_OWNER_ID) if paged else len(rows)
    return SourcesResponse(count=len(rows), total=total, sources=rows)


@router.get("/devices", response_model=DevicesResponse)
async def list_devices(
    limit: _Limit = None,
    offset: _Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> DevicesResponse:
    rows = await registry.list_devices(session, DEFAULT_OWNER_ID, limit=limit, offset=offset)
    paged = limit is not None or offset > 0
    total = await registry.count_devices(session, DEFAULT_OWNER_ID) if paged else len(rows)
    return DevicesResponse(count=len(rows), total=total, devices=rows)


@router.get("/streams", response_model=StreamsResponse)
async def list_streams(
    limit: _Limit = None,
    offset: _Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> StreamsResponse:
    rows = await registry.list_streams(session, DEFAULT_OWNER_ID, limit=limit, offset=offset)
    paged = limit is not None or offset > 0
    total = await registry.count_streams(session, DEFAULT_OWNER_ID) if paged else len(rows)
    return StreamsResponse(count=len(rows), total=total, streams=rows)


@router.get("/streams/{stream_id}", response_model=StreamView)
async def get_stream(stream_id: UUID, session: AsyncSession = Depends(get_session)) -> StreamView:
    row = await registry.get_stream(session, DEFAULT_OWNER_ID, stream_id)
    if row is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return StreamView(**row)


@router.post(
    "/device-identity-links",
    response_model=DeviceIdentityLinkResponse,
    status_code=201,
)
async def create_device_identity_link(
    payload: DeviceIdentityLinkCreate,
    session: AsyncSession = Depends(get_session),
) -> DeviceIdentityLinkResponse:
    confidence = DeviceLinkConfidence(payload.confidence)
    try:
        await fusion_repository.upsert_device_identity_link(
            session,
            owner_id=DEFAULT_OWNER_ID,
            direct_stream_id=payload.direct_stream_id,
            relayed_stream_id=payload.relayed_stream_id,
            status=payload.status,
            confidence=confidence,
            evidence=payload.evidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return DeviceIdentityLinkResponse(
        direct_stream_id=payload.direct_stream_id,
        relayed_stream_id=payload.relayed_stream_id,
        status=payload.status,
        confidence=payload.confidence,
    )


@router.post(
    "/device-identity-links/session-reconciliations",
    response_model=SessionFusionReconciliationResponse,
    status_code=201,
)
async def reconcile_device_identity_link_sessions(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    session: AsyncSession = Depends(get_session),
) -> SessionFusionReconciliationResponse:
    pairs = await fusion_repository.find_session_candidate_pairs(
        session,
        owner_id=DEFAULT_OWNER_ID,
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=limit,
    )

    assigned = 0
    rejected = 0
    for pair in pairs:
        result = await fusion_repository.reconcile_session_pair(
            session,
            owner_id=DEFAULT_OWNER_ID,
            workspace_id=DEFAULT_WORKSPACE_ID,
            provider_subject_id=pair.provider_subject_id,
            direct=pair.direct,
            relayed=pair.relayed,
            device_link=pair.device_link,
            decided_by="operator-api",
        )
        if result.assigned:
            assigned += 1
        else:
            rejected += 1

    if pairs:
        await session.commit()

    return SessionFusionReconciliationResponse(
        matched_pairs=len(pairs),
        assigned=assigned,
        rejected=rejected,
    )
