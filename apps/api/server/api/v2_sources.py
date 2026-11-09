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
not gated by verify_api_key. Authenticity instead comes from Whoop's HMAC
signature (SECURITY-003): we verify base64(HMAC-SHA256(WHOOP_CLIENT_SECRET,
timestamp + raw_body)) against X-WHOOP-Signature before doing any work. When the
secret is unset the integration is unconfigured (no token to fetch with) and the
check warns-and-allows; configured deployments -- the real attack surface --
enforce.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from plugin_sdk import find_plugin_manifest, load_manifest
from storage.timescale.ingest import PostgresIngestStorage

from plugins.sources.whoop import WhoopSource
from plugins.sources.whoop.fetch import WhoopFetchError
from plugins.sources.whoop.oauth import WhoopOAuthError

from .deps import get_session
from .ingest import _is_transient_write_error

router = APIRouter(prefix="/api/v2")
log = logging.getLogger("healthsave.api.v2_sources")

_WHOOP_SECRET_ENV = "WHOOP_CLIENT_SECRET"
_WHOOP_SIG_HEADER = "x-whoop-signature"
_WHOOP_TS_HEADER = "x-whoop-signature-timestamp"


def _verify_whoop_signature(raw_body: bytes, headers: Any) -> None:
    """SECURITY-003: reject forged Whoop webhook events.

    Whoop signs ``base64(HMAC-SHA256(client_secret, timestamp + raw_body))`` and
    sends it in ``X-WHOOP-Signature`` alongside ``X-WHOOP-Signature-Timestamp``.
    When ``WHOOP_CLIENT_SECRET`` is unset the integration is not configured (no
    OAuth token to fetch with, so the handler is already a no-op): we log a loud
    warning and allow, matching the zero-config posture. Configured deployments
    -- the real attack surface -- enforce with a constant-time comparison.
    """
    secret = os.getenv(_WHOOP_SECRET_ENV, "")
    if not secret:
        log.warning(
            "WHOOP_CLIENT_SECRET is not set: Whoop webhook authenticity is NOT "
            "verified. Set it to reject forged events."
        )
        return
    signature = headers.get(_WHOOP_SIG_HEADER)
    timestamp = headers.get(_WHOOP_TS_HEADER)
    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="missing Whoop signature headers")
    digest = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid Whoop signature")


# Whoop answers with one of these when it is busy or failing; it retries a
# webhook that gets a 5xx, so those are worth a retry.
_WHOOP_RETRYABLE = frozenset({408, 425, 429})


def _is_retryable(exc: BaseException) -> bool:
    """True when sending the same event again could succeed.

    A Whoop outage or rate limit, a network failure talking to Whoop, or a
    transient database error. Everything else (a 4xx about the resource, a
    refresh token Whoop refused, a row our storage rejects) fails the same way
    every time, so it is answered with a 4xx and Whoop stops retrying.
    """
    if isinstance(exc, WhoopFetchError):
        status = exc.status_code
        return status is None or status >= 500 or status in _WHOOP_RETRYABLE
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, WhoopOAuthError):
        # A token endpoint outage is retryable; a refused refresh token is not.
        status = exc.status_code
        return status is not None and (status >= 500 or status in _WHOOP_RETRYABLE)
    return _is_transient_write_error(exc)


def _whoop_plugin_yaml() -> Path:
    return find_plugin_manifest("whoop", kind="source", start=Path(__file__))


@router.post("/sources/whoop/webhook")
async def whoop_webhook(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    # SECURITY-003: verify Whoop's HMAC over the RAW body before doing any work.
    raw_body = await request.body()
    _verify_whoop_signature(raw_body, request.headers)
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="whoop webhook body must be JSON") from e
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
        except Exception as e:
            await session.rollback()
            log.exception("whoop webhook failed")
            if _is_retryable(e):
                raise HTTPException(
                    status_code=503, detail="whoop webhook failed; retry later"
                ) from e
            # Deterministic: a retry repeats it, so never a 500.
            raise HTTPException(
                status_code=422, detail=f"whoop webhook could not be applied: {type(e).__name__}"
            ) from e

    log.info("whoop webhook processed: %s", result)
    return {"status": "accepted", "result": result}
