"""GET ``/api/v2/receipts`` — the Local Vault's inspectable chain of custody.

The dashboard's Local Vault Receipt promises "privacy as proof, not prose".
This is the proof surface: the stored intelligence audit trail (settings
changes, consent grants, credential rotations, provider healthchecks — every
event that could change what leaves the host) plus ingest freshness, in one
keyed read. Composes two existing primitives; no new storage.

Deploy note: requires migration 017 (intelligence_settings tables) on the
target DB — the route degrades to an empty event list if the table is absent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import readiness_repository, sync_receipt_repository
from storage.ports import ReadinessRepository, SyncReceiptRepository
from storage.timescale import intelligence as intelligence_repo

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])

_READINESS: ReadinessRepository = readiness_repository()
_SYNC: SyncReceiptRepository = sync_receipt_repository()
# Injectable seam (monkeypatched in tests so route tests stay DB-free).
_INTELLIGENCE = intelligence_repo


@router.get("/receipts")
async def list_receipts(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Egress-relevant audit events (newest first) + ingest freshness."""
    # Ingest freshness first: if the audit table is absent (pre-017 DB), its
    # failed query aborts the transaction and would poison these reads.
    sources = await _READINESS.fetch_canonical_sources(session)
    latest_run = await _SYNC.latest_sync_run(session)

    events_unavailable = False
    try:
        events = await _INTELLIGENCE.default_repository.list_audit_events(session, limit=limit)
    except Exception:  # noqa: BLE001 — table may predate migration 017
        events = []
        events_unavailable = True

    return {
        "events_unavailable": events_unavailable,
        "events": [
            {
                "id": event.id,
                "actor": event.actor,
                "event_type": event.event_type,
                "before_revision": event.before_revision,
                "after_revision": event.after_revision,
                "metadata": event.metadata,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        "count": len(events),
        "ingest": {
            "sources": sources,
            "latest_sync_run": latest_run,
        },
    }
