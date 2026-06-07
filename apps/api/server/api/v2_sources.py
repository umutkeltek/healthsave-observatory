"""POST /api/v2/sources/whoop/webhook — push-driven Whoop ingest (additive v2).

Whoop can push a webhook when a recovery/sleep/workout is scored. This route
fetches the referenced resource through the existing WhoopSource plugin and
persists it via the same IngestStorage path the 30-minute worker poll uses, so a
pushed record is identical to a polled one. The poll remains the default/fallback
ingest path; this route only shortens latency when reachable.

Public ingress required: datahub is self-hosted, so this endpoint must be exposed
to the internet (reverse proxy / tunnel) for Whoop to deliver pushes. With no
public ingress, nothing breaks — the worker poll still ingests on schedule.

Auth note: Whoop cannot send our X-API-Key header, so this route is intentionally
not gated by verify_api_key. Authenticity should come from Whoop's HMAC signature
header — verifying it (WHOOP_CLIENT_SECRET) is the next hardening step; today the
plugin does minimal structural validation of the event only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from plugin_sdk import load_manifest
from storage.timescale.ingest import PostgresIngestStorage

from plugins.sources.whoop import WhoopSource

from .deps import get_session

router = APIRouter(prefix="/api/v2")
log = logging.getLogger("healthsave.api.v2_sources")


def _whoop_plugin_yaml() -> Path:
    return Path(__file__).resolve().parents[4] / "plugins" / "sources" / "whoop" / "plugin.yaml"


@router.post("/sources/whoop/webhook")
async def whoop_webhook(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    event = await request.json()
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="whoop webhook body must be a JSON object")

    plugin = WhoopSource(load_manifest(_whoop_plugin_yaml()))
    storage = PostgresIngestStorage()

    async with httpx.AsyncClient(timeout=30.0) as http:
        try:
            result = await plugin.handle_webhook(
                {"event": event, "storage": storage, "session": session, "http_client": http}
            )
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception:
            await session.rollback()
            log.exception("whoop webhook failed")
            raise

    log.info("whoop webhook processed: %s", result)
    return {"status": "accepted", "result": result}
