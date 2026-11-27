"""Shared FastAPI dependencies (auth, session)."""

import hmac
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from storage.timescale.api_keys import ApiKeyRecord, find_api_key, hash_api_key

from ..db.session import get_session
from .access import LEGACY_PRINCIPAL, Principal, authorize, remember

log = logging.getLogger("healthsave")

API_KEY = os.getenv("API_KEY", "")
# SECURITY-001 (default-deny): when no API_KEY is configured, the PHI ingest/read
# surface is REFUSED (503) unless the operator has explicitly acknowledged open
# mode via ALLOW_NO_AUTH — it no longer fails open silently. The local
# `docker compose up` path sets ALLOW_NO_AUTH=true (zero-config demo stays open,
# with a loud startup warning); a real deploy mints an API_KEY (setup.sh /
# deploy/remote-vm/deploy.sh), so a deployment is always key-gated.
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").strip().lower() in ("1", "true", "yes", "on")


def _matches_legacy_key(key: str) -> bool:
    """Constant-time check against the ``.env`` key (bytes, so any header text is safe)."""

    return bool(API_KEY) and hmac.compare_digest(
        key.encode("utf-8", "surrogatepass"), API_KEY.encode("utf-8", "surrogatepass")
    )


@dataclass(frozen=True, slots=True)
class KeyLookup:
    """Outcome of looking a non-legacy key up in ``api_keys`` (migration 029)."""

    record: ApiKeyRecord | None
    failed: bool = False


async def lookup_participant_key(
    request: Request, session: Any = Depends(get_session)
) -> KeyLookup | None:
    """Look a presented key up in ``api_keys`` unless it is the legacy key.

    The legacy ``API_KEY`` (and a missing key) never touches the database, so
    a phone on the ``.env`` key sees exactly the pre-029 request path. The
    lookup runs on the request's own session and is rolled back before the
    route body starts, so the route opens its transaction exactly as before.
    """

    key = request.headers.get("x-api-key") or ""
    if not key or _matches_legacy_key(key):
        return None
    try:
        record = await find_api_key(session, hash_api_key(key))
    except Exception:  # noqa: BLE001 - any lookup failure is decided by verify_api_key
        log.warning("participant key lookup failed", exc_info=True)
        await _quiet_rollback(session)
        return KeyLookup(record=None, failed=True)
    await _quiet_rollback(session)
    return KeyLookup(record=record)


async def _quiet_rollback(session: Any) -> None:
    rollback = getattr(session, "rollback", None)
    if not callable(rollback):
        return
    try:
        await rollback()
    except Exception:  # noqa: BLE001 - the lookup never fails a request on cleanup
        log.debug("rollback after participant key lookup failed", exc_info=True)


def verify_api_key(
    x_api_key: str = Header(default=""),
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
    lookup: Annotated[KeyLookup | None, Depends(lookup_participant_key)] = None,
):
    """Gate the PHI surface and record who is calling.

    SECURITY-001 (default-deny): when no ``API_KEY`` is configured, refuse the
    request with ``503`` unless the operator has explicitly acknowledged open
    mode via ``ALLOW_NO_AUTH`` — the surface no longer fails open silently.
    SECURITY-006: when a key is configured the comparison is constant-time so the
    key cannot be recovered via response timing.

    Participant keys (migration 029), in order:

    1. The legacy ``API_KEY`` is the admin key for the primary person, chosen
       per request exactly as before (no database call).
    2. A live ``api_keys`` row authenticates as its scope and owner, in keyed
       and in open mode; a participant key may only call the routes
       ``server.api.access`` allows its scope (403 otherwise).
    3. A revoked row is 401 in every mode: a revoked phone must never fall
       through into the primary person's data.
    4. A lookup that failed is 503 when a key is configured (transient; the
       phone retries). Open mode keeps its open pass.
    5. Anything else behaves exactly as before (401, open pass, or 503).
    """
    key = x_api_key or ""
    found = lookup if isinstance(lookup, KeyLookup) else None
    if _matches_legacy_key(key):
        remember(request, LEGACY_PRINCIPAL)
        return
    if found is not None and found.record is not None:
        record = found.record
        if record.revoked:
            raise HTTPException(status_code=401, detail="api_key_revoked")
        principal = Principal(
            scope=record.scope,  # type: ignore[arg-type]
            owner_id=None if record.scope == "admin" else record.owner_id,
            key_id=record.id,
            label=record.label,
        )
        if request is not None:
            authorize(principal, request)
        remember(request, principal)
        return
    if found is not None and found.failed and API_KEY:
        raise HTTPException(
            status_code=503,
            detail="api_key_lookup_unavailable: the key store did not answer; retry",
        )
    if not API_KEY:
        if ALLOW_NO_AUTH:
            remember(request, LEGACY_PRINCIPAL)
            return
        raise HTTPException(
            status_code=503,
            detail="auth_not_configured: set API_KEY, or ALLOW_NO_AUTH=true to run open",
        )
    raise HTTPException(status_code=401, detail="Invalid API key")


def warn_if_auth_disabled() -> None:
    """Emit a loud startup signal when the PHI surface is unauthenticated.

    SECURITY-001: API_KEY defaulting to ``""`` silently disabled auth on a
    backend that stores PHI and (via the Whoop webhook) is meant to be
    internet-facing. Zero-config startup is preserved, but it must not be
    SILENT: an operator who has not set API_KEY and has not explicitly opted
    into ALLOW_NO_AUTH gets a prominent warning on every boot.
    """
    if API_KEY:
        return
    if ALLOW_NO_AUTH:
        log.warning(
            "AUTH DISABLED by explicit ALLOW_NO_AUTH opt-in: ingest and all PHI "
            "reads are UNAUTHENTICATED. Anyone who can reach this server can read "
            "and write health data."
        )
        return
    log.warning(
        "SECURITY: API_KEY is not set and ALLOW_NO_AUTH is not acknowledged -- the "
        "PHI surface (POST /api/apple/batch and all PHI reads) is REFUSED with 503 "
        "until you set API_KEY to require a key, or ALLOW_NO_AUTH=true to run open. "
        "This backend stores PHI."
    )


__all__ = [
    "ALLOW_NO_AUTH",
    "API_KEY",
    "KeyLookup",
    "get_session",
    "lookup_participant_key",
    "verify_api_key",
    "warn_if_auth_disabled",
]
