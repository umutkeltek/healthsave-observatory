"""GET ``/api/v2/changes`` — a cheap change signal for near-real-time UIs.

The dashboard polls this (~30s) instead of re-rendering blind: the response is
a tiny fingerprint of "did anything land?" — latest ingest per source, latest
sync run, latest narrative. ``version_token`` doubles as an ETag: send
``If-None-Match`` and an unchanged state answers ``304`` with no body, so the
poll costs almost nothing. SSE stays the documented upgrade path if sub-5s
latency is ever needed (agent_events was designed for it); for a single-user
self-hosted dashboard a 30s conditional poll is perceptually identical.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import (
    briefing_repository,
    readiness_repository,
    sync_receipt_repository,
)
from storage.ports import BriefingRepository, ReadinessRepository, SyncReceiptRepository

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])

_READINESS: ReadinessRepository = readiness_repository()
_SYNC: SyncReceiptRepository = sync_receipt_repository()
_BRIEFINGS: BriefingRepository = briefing_repository()


def _token(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode())
    return f'"{digest.hexdigest()[:24]}"'


@router.get("/changes", response_model=None)
async def changes(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response | dict:
    """Latest-activity fingerprint with ETag/304 semantics."""
    sources = await _READINESS.fetch_canonical_sources(session)
    last_ingested_at = max(
        (s.get("last_ingested_at") for s in sources if s.get("last_ingested_at")),
        default=None,
    )
    latest_run = await _SYNC.latest_sync_run(session)
    narratives = await _BRIEFINGS.latest_narratives_by_type(session)
    last_narrative_at = max(
        (row.created_at for row in narratives.values() if row is not None and row.created_at),
        default=None,
    )

    body = {
        "last_ingested_at": last_ingested_at.isoformat() if last_ingested_at else None,
        "latest_sync_run": latest_run,
        "last_narrative_at": last_narrative_at.isoformat() if last_narrative_at else None,
    }
    token = _token(body)
    if token in _client_etags(request.headers.get("if-none-match")):
        return Response(status_code=304, headers={"ETag": token})
    response.headers["ETag"] = token
    return {**body, "version_token": token}


def _client_etags(header: str | None) -> set[str]:
    """Parse If-None-Match tolerantly: multi-value lists and proxy-weakened
    ``W/"…"`` forms both still match (a gzip proxy downgrading the ETag must
    not silently defeat every 304)."""
    if not header:
        return set()
    out: set[str] = set()
    for part in header.split(","):
        candidate = part.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate:
            out.add(candidate)
    return out
