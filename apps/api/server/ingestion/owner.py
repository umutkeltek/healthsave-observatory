"""Owner-id resolution for multi-user / household ingestion.

The schema treats every metric row as belonging to an owner (a UUID).
Existing single-user installs and HealthSave clients that don't know
about the X-User-Id header default to a fixed sentinel UUID — that
keeps backward compatibility with v1.0 deployments untouched.
"""

from __future__ import annotations

from uuid import UUID

# Sentinel used when no X-User-Id header is supplied. Matches the
# schema-level DEFAULT, so existing rows + legacy clients all line up.
DEFAULT_OWNER_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")

# Header name on the wire. Lower-case for httpx/requests friendliness;
# FastAPI Request.headers lookups are case-insensitive either way.
OWNER_HEADER: str = "x-user-id"


def resolve_owner_id(raw: str | None) -> UUID:
    """Parse an X-User-Id header value into a UUID, falling back to the sentinel.

    Empty or missing values resolve to ``DEFAULT_OWNER_ID``. Malformed
    values raise ``ValueError`` so the caller can return HTTP 400.
    """
    if raw is None:
        return DEFAULT_OWNER_ID
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_OWNER_ID
    return UUID(cleaned)
