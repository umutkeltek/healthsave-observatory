"""Shared FastAPI dependencies (auth, session)."""

import hmac
import logging
import os

from fastapi import Header, HTTPException

from ..db.session import get_session

log = logging.getLogger("healthsave")

API_KEY = os.getenv("API_KEY", "")
# SECURITY-001 (default-deny): when no API_KEY is configured, the PHI ingest/read
# surface is REFUSED (503) unless the operator has explicitly acknowledged open
# mode via ALLOW_NO_AUTH — it no longer fails open silently. The local
# `docker compose up` path sets ALLOW_NO_AUTH=true (zero-config demo stays open,
# with a loud startup warning); a real deploy mints an API_KEY (setup.sh /
# deploy/remote-vm/deploy.sh), so a deployment is always key-gated.
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").strip().lower() in ("1", "true", "yes", "on")


def verify_api_key(x_api_key: str = Header(default="")):
    """Gate the PHI surface.

    SECURITY-001 (default-deny): when no ``API_KEY`` is configured, refuse the
    request with ``503`` unless the operator has explicitly acknowledged open
    mode via ``ALLOW_NO_AUTH`` — the surface no longer fails open silently.
    SECURITY-006: when a key is configured the comparison is constant-time so the
    key cannot be recovered via response timing.
    """
    if not API_KEY:
        if ALLOW_NO_AUTH:
            return
        raise HTTPException(
            status_code=503,
            detail="auth_not_configured: set API_KEY, or ALLOW_NO_AUTH=true to run open",
        )
    if not hmac.compare_digest(x_api_key or "", API_KEY):
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
    "get_session",
    "verify_api_key",
    "warn_if_auth_disabled",
]
