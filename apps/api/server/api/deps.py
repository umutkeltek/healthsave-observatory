"""Shared FastAPI dependencies (auth, session)."""

import hmac
import logging
import os

from fastapi import Header, HTTPException

from ..db.session import get_session

log = logging.getLogger("healthsave")

API_KEY = os.getenv("API_KEY", "")
# SECURITY-001: explicit opt-in for running the PHI ingest/read surface with NO
# auth. When API_KEY is unset and this is not true, the app still serves (so
# zero-config `docker compose up` keeps working) but logs a loud warning at
# startup every boot rather than failing open silently. See warn_if_auth_disabled.
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").strip().lower() in ("1", "true", "yes", "on")


def verify_api_key(x_api_key: str = Header(default="")):
    """Require a matching ``X-API-Key`` when an API_KEY is configured.

    SECURITY-006: the comparison is constant-time so the key cannot be recovered
    via response timing. When API_KEY is empty, auth is disabled (open mode) and
    the operator is warned loudly at startup by :func:`warn_if_auth_disabled`.
    """
    if not API_KEY:
        return
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
        "SECURITY: API_KEY is not set -- ingest (POST /api/apple/batch) and all "
        "PHI reads are UNAUTHENTICATED. Set API_KEY to require a key, or set "
        "ALLOW_NO_AUTH=true to acknowledge open mode. This backend stores PHI; do "
        "not expose it to untrusted networks without a key."
    )


__all__ = [
    "ALLOW_NO_AUTH",
    "API_KEY",
    "get_session",
    "verify_api_key",
    "warn_if_auth_disabled",
]
