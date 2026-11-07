"""Who is calling, and which routes a participant key may use.

One Observatory per coach or clinic, one key per participant (migration
029). The legacy ``API_KEY`` stays the admin key for the primary person.
A participant key is bound to its own ``owner_id``; this module is the one
place that says which routes such a key may reach.

The policy is keyed by route template and method, so it is decided after
routing, inside the auth dependency. A route nobody classified is
admin-only: a surface another change adds later stays closed to
participant keys until someone puts it in a table below on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request

from ..ingestion.owner import DEFAULT_OWNER_ID, PRINCIPAL_STATE_KEY

Scope = Literal["admin", "read", "ingest"]
RouteClass = Literal["phone", "owner_read", "admin"]

#: The surface a shipped HealthSave phone calls. A participant ingest key
#: reaches exactly these, always as its own owner.
PHONE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/apple/batch"),
        ("GET", "/api/apple/status"),
        ("GET", "/api/apple/coverage"),
        ("POST", "/api/v2/apple/batch"),
        ("GET", "/api/v2/sync/runs/latest"),
        ("GET", "/api/v2/sync/runs/{sync_run_id}"),
        ("PUT", "/api/v2/sync/runs/{sync_run_id}/summary"),
    }
)

#: v2 reads whose storage is owner-scoped. They take ``?owner=``: an admin
#: may name any owner (default: the default owner); a read key gets its own.
OWNER_READ_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v2/metrics/{metric_id}/series"),
        ("GET", "/api/v2/series"),
        ("GET", "/api/v2/export/metrics"),
        ("GET", "/api/v2/export"),
        ("GET", "/api/v2/sources"),
        ("GET", "/api/v2/devices"),
        ("GET", "/api/v2/streams"),
        ("GET", "/api/v2/streams/{stream_id}"),
        ("GET", "/api/v2/readiness"),
        ("GET", "/api/v2/year/{year}"),
    }
)

OWNER_QUERY_DESCRIPTION = (
    "Owner whose data to read. Admin keys may name any owner (default: the "
    "default owner); a participant read key may only name its own."
)


@dataclass(frozen=True, slots=True)
class Principal:
    """The caller behind one request.

    ``owner_id`` is set for participant keys (ingest/read): every request
    they make is that owner. Admin principals (the legacy ``API_KEY``, open
    mode, admin-scope keys) carry ``None`` and pick the owner per request
    exactly as before participant keys existed.
    """

    scope: Scope
    owner_id: UUID | None = None
    key_id: UUID | None = None
    label: str | None = None

    @property
    def bound(self) -> bool:
        return self.scope != "admin" and self.owner_id is not None


LEGACY_PRINCIPAL = Principal(scope="admin")


def route_class(method: str, path: str) -> RouteClass:
    verb = "GET" if method.upper() == "HEAD" else method.upper()
    if (verb, path) in PHONE_ROUTES:
        return "phone"
    if (verb, path) in OWNER_READ_ROUTES:
        return "owner_read"
    return "admin"


def is_allowed(principal: Principal, method: str, path: str) -> bool:
    if principal.scope == "admin":
        return True
    kind = route_class(method, path)
    if principal.scope == "ingest":
        return kind == "phone"
    # read: GETs on the phone surface and the owner-scoped reads, own owner only.
    return method.upper() in ("GET", "HEAD") and kind in ("phone", "owner_read")


def route_template(request: Any) -> tuple[str, str]:
    """``(method, path template)`` of the matched route, else the raw path."""

    scope = getattr(request, "scope", None) or {}
    route = scope.get("route") if isinstance(scope, dict) else None
    path = getattr(route, "path", None) or str(getattr(getattr(request, "url", None), "path", ""))
    return str(getattr(request, "method", "GET")), path


def authorize(principal: Principal, request: Any) -> None:
    """403 when a participant key calls a route outside its scope."""

    method, path = route_template(request)
    if not is_allowed(principal, method, path):
        raise HTTPException(
            status_code=403,
            detail=f"api_key_scope: a {principal.scope} key cannot call {method} {path}",
        )


def remember(request: Any, principal: Principal) -> None:
    state = getattr(request, "state", None)
    if state is not None:
        setattr(state, PRINCIPAL_STATE_KEY, principal)


def principal_of(request: Any) -> Principal | None:
    state = getattr(request, "state", None)
    principal = getattr(state, PRINCIPAL_STATE_KEY, None) if state is not None else None
    return principal if isinstance(principal, Principal) else None


def _read_owner(
    request: Request,
    owner: UUID | None = Query(default=None, description=OWNER_QUERY_DESCRIPTION),
) -> UUID:
    """Owner for an owner-scoped v2 read (runs after the auth dependency)."""

    principal = principal_of(request)
    if principal is not None and principal.bound:
        if owner is not None and owner != principal.owner_id:
            raise HTTPException(
                status_code=403,
                detail="owner_not_allowed: a participant key reads only its own owner",
            )
        return principal.owner_id  # type: ignore[return-value]
    return owner or DEFAULT_OWNER_ID


#: Route parameter type for owner-scoped v2 reads. Direct callers (unit
#: tests) that omit it get the default owner, exactly the pre-029 behaviour.
ReadOwner = Annotated[UUID, Depends(_read_owner)]


__all__ = [
    "LEGACY_PRINCIPAL",
    "OWNER_QUERY_DESCRIPTION",
    "OWNER_READ_ROUTES",
    "PHONE_ROUTES",
    "Principal",
    "ReadOwner",
    "authorize",
    "is_allowed",
    "principal_of",
    "remember",
    "route_class",
    "route_template",
]
