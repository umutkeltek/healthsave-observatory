"""Owner-id resolution for multi-user / household ingestion.

The schema treats every metric row as belonging to an owner (a UUID).
Existing single-user installs and HealthSave clients that don't know
about the X-User-Id header default to a fixed sentinel UUID — that
keeps backward compatibility with v1.0 deployments untouched.
"""

from __future__ import annotations

import os
from uuid import UUID

# Sentinel used when no X-User-Id header is supplied. Matches the
# schema-level DEFAULT, so existing rows + legacy clients all line up.
DEFAULT_OWNER_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")

# Header name on the wire. Lower-case for httpx/requests friendliness;
# FastAPI Request.headers lookups are case-insensitive either way.
OWNER_HEADER: str = "x-user-id"

# SECURITY-002: with a single shared API key there is no way to authenticate
# that a caller may act as a given owner, so honoring an arbitrary X-User-Id is
# a cross-tenant spoof/read vector. By default the header is therefore IGNORED
# and every request maps to DEFAULT_OWNER_ID. Operators running a trusted-LAN
# household can opt back in with ALLOW_MULTI_USER=true; that flag is the seam
# where real per-owner-key authentication will plug in when multi-tenant lands.
ALLOW_MULTI_USER = os.getenv("ALLOW_MULTI_USER", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_owner_id(raw: str | None) -> UUID:
    """Resolve the owning UUID for a request.

    SECURITY-002: unless ``ALLOW_MULTI_USER`` is enabled the client-supplied
    X-User-Id is NOT trusted -- every request resolves to ``DEFAULT_OWNER_ID``
    and the spoof vector is closed. When multi-user is explicitly enabled, an
    empty/missing value still falls back to the sentinel and a malformed value
    raises ``ValueError`` so the caller can return HTTP 400.
    """
    if not ALLOW_MULTI_USER:
        return DEFAULT_OWNER_ID
    if raw is None:
        return DEFAULT_OWNER_ID
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_OWNER_ID
    return UUID(cleaned)
