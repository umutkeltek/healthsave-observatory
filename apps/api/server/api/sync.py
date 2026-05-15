"""HealthSave setup diagnostics and sync receipt operator endpoints.

These endpoints are additive v2 surfaces. They do not change the released
HealthSave v1 ingest/status contract, but they make the existing iOS wire
headers observable so operators can prove that a sync reached Data Hub.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from storage.timescale import sync_receipts

from . import deps
from .deps import get_session, verify_api_key

router = APIRouter()


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
        "coverage_endpoint": "/api/v2/sync/coverage",
        "grafana_required": False,
        "wrong_port_hint": (
            "If you see Grafana auth JSON or Homepage HTML 404, the app is pointed "
            "at the wrong port. Use the Data Hub API base URL, not Grafana/Homepage."
        ),
    }


@router.get("/api/v2/sync/runs/latest", dependencies=[Depends(verify_api_key)])
async def latest_sync_run(session: Any = Depends(get_session)) -> dict:
    """Summarize the most recently observed HealthSave sync run."""

    return await sync_receipts.latest_sync_run(session)


@router.get("/api/v2/sync/coverage", dependencies=[Depends(verify_api_key)])
async def sync_coverage(session: Any = Depends(get_session)) -> dict:
    """Return metric-level receipt coverage from the Data Hub side."""

    return await sync_receipts.sync_coverage(session)
