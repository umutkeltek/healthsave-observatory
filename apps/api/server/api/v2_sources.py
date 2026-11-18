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

Replay: a signed delivery is honoured only while its signed timestamp is within
five minutes of the server clock, and an identical signed delivery that arrives
again inside that window is acknowledged without being applied a second time.
That memory lives in this process and needs no table, because applying an event
is idempotent: the route never trusts the event body's data, it re-fetches the
resource from Whoop and upserts it on the row's natural key (or marks a deleted
workout superseded, which a second time changes nothing). A replay that slips
past the memory (process restart, entry evicted at the size cap) therefore
costs one more Whoop API call and writes only what Whoop holds now, exactly as
the next poll would; the event body cannot inject data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, NamedTuple

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
# How far the signed timestamp may sit from the server clock, either way.
_WHOOP_SIGNATURE_MAX_SKEW_S = 5 * 60
# Milliseconds since the epoch stay 13 digits until the year 2286; anything much
# longer is not a timestamp (and a huge one would trip Python's int-string limit).
_WHOOP_TS_MAX_DIGITS = 16
# Safety cap on remembered deliveries. Whoop sends a handful of events per scored
# activity, so a five-minute window never comes close.
_WHOOP_RECENT_DELIVERIES_MAX = 4096


class _SignedDelivery(NamedTuple):
    """One webhook delivery whose signature checked out."""

    signature: str
    signed_at: float  # Unix seconds


def _verify_whoop_signature(
    raw_body: bytes, headers: Any, *, now: float | None = None
) -> _SignedDelivery | None:
    """SECURITY-003: reject forged or stale Whoop webhook events.

    Whoop signs ``base64(HMAC-SHA256(client_secret, timestamp + raw_body))`` and
    sends it in ``X-WHOOP-Signature`` alongside ``X-WHOOP-Signature-Timestamp``,
    whose value is milliseconds since the Unix epoch. A delivery is rejected
    with 401 when either header is missing, the timestamp is not a plain number,
    the signature does not match (constant-time comparison), or the signed time
    is more than five minutes from ``now`` in either direction.

    When ``WHOOP_CLIENT_SECRET`` is unset the integration is not configured (no
    OAuth token to fetch with, so the handler is already a no-op): we log a loud
    warning and allow, matching the zero-config posture, and return ``None``.
    Otherwise the verified delivery is returned for duplicate suppression.
    """
    secret = os.getenv(_WHOOP_SECRET_ENV, "")
    if not secret:
        log.warning(
            "WHOOP_CLIENT_SECRET is not set: Whoop webhook authenticity is NOT "
            "verified. Set it to reject forged events."
        )
        return None
    signature = headers.get(_WHOOP_SIG_HEADER)
    timestamp = headers.get(_WHOOP_TS_HEADER)
    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="missing Whoop signature headers")
    if not (timestamp.isascii() and timestamp.isdigit() and len(timestamp) <= _WHOOP_TS_MAX_DIGITS):
        raise HTTPException(status_code=401, detail="invalid Whoop signature timestamp")
    digest = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest)
    # Compare bytes: a header with non-ASCII characters must be a 401, and
    # compare_digest refuses non-ASCII str.
    if not hmac.compare_digest(expected, signature.encode()):
        raise HTTPException(status_code=401, detail="invalid Whoop signature")
    signed_at = int(timestamp) / 1000
    current = time.time() if now is None else now
    if abs(current - signed_at) > _WHOOP_SIGNATURE_MAX_SKEW_S:
        raise HTTPException(status_code=401, detail="stale Whoop signature timestamp")
    return _SignedDelivery(signature=signature, signed_at=signed_at)


class _RecentDeliveries:
    """Signed deliveries this process has applied, kept while they are still fresh.

    A delivery is keyed by its signature: the HMAC covers the timestamp and the
    raw body, so the same signature means the same delivery. An entry is kept
    until its signed time leaves the freshness window; after that the signature
    check rejects the delivery as stale anyway. Calls are synchronous, so on the
    single event loop a check-and-claim cannot interleave with another request.
    """

    def __init__(self, max_entries: int) -> None:
        self._expires_at: OrderedDict[str, float] = OrderedDict()
        self._max_entries = max_entries

    def claim(self, delivery: _SignedDelivery, *, now: float) -> bool:
        """Record ``delivery``; False when it is already recorded (a duplicate)."""
        # Entries arrive roughly in expiry order; one a little out of order is
        # dropped late, which is harmless (it is stale by then).
        while self._expires_at and next(iter(self._expires_at.values())) < now:
            self._expires_at.popitem(last=False)
        if delivery.signature in self._expires_at:
            return False
        self._expires_at[delivery.signature] = delivery.signed_at + _WHOOP_SIGNATURE_MAX_SKEW_S
        while len(self._expires_at) > self._max_entries:
            self._expires_at.popitem(last=False)
        return True

    def release(self, delivery: _SignedDelivery) -> None:
        """Forget ``delivery`` so a retry of it is applied (it did not succeed)."""
        self._expires_at.pop(delivery.signature, None)

    def clear(self) -> None:
        self._expires_at.clear()


_RECENT_WHOOP_DELIVERIES = _RecentDeliveries(_WHOOP_RECENT_DELIVERIES_MAX)


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
    now = time.time()
    delivery = _verify_whoop_signature(raw_body, request.headers, now=now)
    if delivery is not None and not _RECENT_WHOOP_DELIVERIES.claim(delivery, now=now):
        # Already applied: answer 2xx so Whoop stops sending it, and do nothing.
        log.info("whoop webhook: duplicate delivery ignored (signed at %.3f)", delivery.signed_at)
        return {"status": "accepted", "result": {"accepted": 0, "rejected": 0, "duplicate": 1}}
    try:
        return await _apply_whoop_event(raw_body, session)
    except BaseException:
        # Not applied (error answer, or the request was cancelled): Whoop
        # retries it, and that retry must be applied, not taken for a replay.
        if delivery is not None:
            _RECENT_WHOOP_DELIVERIES.release(delivery)
        raise


async def _apply_whoop_event(raw_body: bytes, session: Any) -> dict[str, Any]:
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
