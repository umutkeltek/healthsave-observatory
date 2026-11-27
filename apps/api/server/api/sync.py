"""HealthSave setup diagnostics and sync receipt operator endpoints.

These endpoints are additive v2 surfaces. They do not change the released
HealthSave v1 ingest/status contract, but they make the existing iOS wire
headers observable so operators can prove that a sync reached Data Hub.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from storage.defaults import sync_receipt_repository
from storage.ports import SyncReceiptRepository

from ..ingestion.owner import OWNER_HEADER, participant_owner_id, resolve_owner_id
from . import deps
from .deps import get_session, verify_api_key

router = APIRouter()
_SYNC_RECEIPTS: SyncReceiptRepository = sync_receipt_repository()


@router.get("/api/v2/setup/diagnostics")
async def setup_diagnostics() -> dict:
    """Return a no-secret setup fingerprint for humans and clients.

    This is intentionally unauthenticated: it exposes no health data and helps
    users distinguish the Data Hub API from nearby Grafana/Homepage ports before
    they troubleshoot keys or sync.
    """

    return {
        "service": "health-data-hub",
        "kind": "HealthSave Data Hub API",
        "status": "ok",
        "auth_required": bool(deps.API_KEY),
        "health_endpoint": "/api/health",
        "status_endpoint": "/api/apple/status",
        "ingest_endpoint": "/api/apple/batch",
        "latest_sync_endpoint": "/api/v2/sync/runs/latest",
        "run_summary_endpoint": "/api/v2/sync/runs/{sync_run_id}/summary",
        "coverage_endpoint": "/api/v2/sync/coverage",
        "anomalies_endpoint": "/api/v2/sync/anomalies",
        "grafana_required": False,
        "wrong_port_hint": (
            "If you see Grafana auth JSON or Homepage HTML 404, the app is pointed "
            "at the wrong port. Use the Data Hub API base URL, not Grafana/Homepage."
        ),
    }


def _caller_owner_id(request: Request | None) -> UUID | None:
    """Whose runs a phone-surface read sees: the participant key's owner, else
    the X-User-Id resolution every phone route uses (the default owner unless
    ALLOW_MULTI_USER). ``None`` only for direct calls without a request (the
    response-corpus generator), which keep the unscoped pre-029 query."""

    if request is None:
        return None
    try:
        return participant_owner_id(request) or resolve_owner_id(request.headers.get(OWNER_HEADER))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {OWNER_HEADER}: {exc}") from exc


@router.get("/api/v2/sync/runs/latest", dependencies=[Depends(verify_api_key)])
async def latest_sync_run(
    session: Any = Depends(get_session),
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
) -> dict:
    """Summarize the most recently observed HealthSave sync run."""

    owner_id = _caller_owner_id(request)
    if owner_id is None:
        return await _SYNC_RECEIPTS.latest_sync_run(session)
    return await _SYNC_RECEIPTS.latest_sync_run(session, owner_id=owner_id)


@router.get("/api/v2/sync/runs/{sync_run_id}", dependencies=[Depends(verify_api_key)])
async def sync_run(
    sync_run_id: str,
    session: Any = Depends(get_session),
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
) -> dict:
    """Return the delivery receipt summary for one HealthSave sync run."""

    owner_id = _caller_owner_id(request)
    if owner_id is None:
        return await _SYNC_RECEIPTS.sync_run(session, sync_run_id)
    return await _SYNC_RECEIPTS.sync_run(session, sync_run_id, owner_id=owner_id)


class SyncRunSummaryPayload(BaseModel):
    """What a HealthSave client says about a run it just closed.

    Receipts are written per HTTP batch, so a run that had nothing to send left
    no trace on the server and ``GET /api/v2/sync/runs/latest`` kept answering
    with the previous run. This body is the run's existence proof: one small
    PUT per completed run, idempotent on the run id. It carries counts and
    metric NAMES only — never a health value.

    ``extra='allow'`` keeps the shape forward-compatible (a newer client may add
    keys an older server ignores); the enumerated fields are validated
    deterministically and a bad value is a 422, never a 500.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    outcome: Literal["completed", "failed"]
    delivery: Literal["none", "foreground", "background_queued"]
    records_sent: int = Field(ge=0)
    metrics_checked: list[str] = Field(default_factory=list, max_length=4096)
    metrics_with_changes: list[str] = Field(default_factory=list, max_length=4096)
    trigger: str | None = Field(default=None, max_length=64)
    intent: Literal["latest_changes", "backfill", "date_range"] | None = None
    error_class: str | None = Field(default=None, max_length=128)
    client_platform: str | None = Field(default=None, max_length=64)
    client_app_version: str | None = Field(default=None, max_length=64)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@router.put(
    "/api/v2/sync/runs/{sync_run_id}/summary",
    dependencies=[Depends(verify_api_key)],
)
async def put_sync_run_summary(
    sync_run_id: str,
    payload: SyncRunSummaryPayload,
    request: Request,
    session: Any = Depends(get_session),
) -> dict:
    """Record (or replace) the client's closing summary for one sync run.

    Optional for third-party servers, like every ``/api/v2/sync/*`` route: a
    client treats 404/405 here as "not supported" and carries on. When present,
    it is what lets ``GET /api/v2/sync/runs/latest`` report a run that sent
    nothing as the latest run instead of silently repeating the previous one.
    """

    run_id = sync_run_id.strip()
    if not run_id or len(run_id) > 128:
        raise HTTPException(status_code=422, detail="sync_run_id must be 1-128 characters")
    try:
        owner_id = participant_owner_id(request) or resolve_owner_id(
            request.headers.get(OWNER_HEADER)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {OWNER_HEADER}: {exc}") from exc

    recorded = await _SYNC_RECEIPTS.record_sync_run_summary(
        session,
        owner_id=owner_id,
        sync_run_id=run_id,
        outcome=payload.outcome,
        delivery=payload.delivery,
        records_sent=payload.records_sent,
        metrics_checked=payload.metrics_checked,
        metrics_with_changes=payload.metrics_with_changes,
        trigger=payload.trigger,
        intent=payload.intent,
        error_class=payload.error_class,
        client_platform=payload.client_platform,
        client_app_version=payload.client_app_version,
        client_started_at=payload.started_at,
        client_completed_at=payload.completed_at,
    )
    await session.commit()
    return recorded


@router.get("/api/v2/sync/coverage", dependencies=[Depends(verify_api_key)])
async def sync_coverage(session: Any = Depends(get_session)) -> dict:
    """Return metric-level receipt and destination sample coverage."""

    return await _SYNC_RECEIPTS.sync_coverage(session)


@router.get("/api/v2/sync/anomalies", dependencies=[Depends(verify_api_key)])
async def sync_anomalies(session: Any = Depends(get_session)) -> dict:
    """Detect suspicious sync behavior visible from server receipts."""

    return await _SYNC_RECEIPTS.sync_anomalies(session)
