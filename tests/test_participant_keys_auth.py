"""Participant key resolution and route scopes (migration 029).

The legacy ``API_KEY`` must behave exactly as before (and never touch the
database); a participant key authenticates as its owner and scope; a
revoked key is 401 in every mode; a key calling outside its scope is 403.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from server.api import access, deps
from server.api.access import (
    OWNER_READ_ROUTES,
    PHONE_ROUTES,
    Principal,
    is_allowed,
    principal_of,
    route_class,
)
from server.db.session import get_session
from server.ingestion.owner import DEFAULT_OWNER_ID, resolve_request_owner_id
from server.main import app
from storage.timescale.api_keys import hash_api_key

LEGACY = "legacy-admin-key"
ALICE_OWNER = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")
KEYS = {
    "alice-ingest": {"scope": "ingest", "owner_id": ALICE_OWNER, "revoked_at": None},
    "alice-read": {"scope": "read", "owner_id": ALICE_OWNER, "revoked_at": None},
    "coach-admin": {"scope": "admin", "owner_id": DEFAULT_OWNER_ID, "revoked_at": None},
    "bob-revoked": {
        "scope": "ingest",
        "owner_id": uuid4(),
        "revoked_at": datetime(2026, 11, 1, tzinfo=UTC),
    },
}
BY_HASH = {hash_api_key(key): value for key, value in KEYS.items()}


class _Result:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class _KeySession:
    """Answers the api_keys lookup; records every statement."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append(sql)
        if self.fail:
            raise ConnectionError("key store down")
        if "FROM api_keys WHERE key_hash" in sql:
            entry = BY_HASH.get((params or {}).get("key_hash"))
            if entry is None:
                return _Result()
            return _Result(
                SimpleNamespace(
                    _mapping={
                        "id": uuid4(),
                        "label": "Alice",
                        "created_at": None,
                        **entry,
                    }
                )
            )
        raise AssertionError(f"unexpected SQL in auth test: {sql}")

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", LEGACY)
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)


@pytest.fixture
def open_mode(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", "")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", True)


@pytest.fixture
def session():
    fake = _KeySession()
    app.dependency_overrides[get_session] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_session, None)


class _Req:
    """Request stand-in: headers, a state bag, a matched route."""

    def __init__(self, key: str = "", method: str = "GET", path: str = "/api/apple/status"):
        self.headers = {"x-api-key": key} if key else {}
        self.state = SimpleNamespace()
        self.method = method
        self.scope = {"route": SimpleNamespace(path=path)}


async def _resolve(key: str, *, method="GET", path="/api/apple/status", session=None):
    request = _Req(key, method, path)
    lookup = await deps.lookup_participant_key(request, session or _KeySession())
    deps.verify_api_key(x_api_key=key, request=request, lookup=lookup)
    return principal_of(request), request


# ─── legacy key: unchanged, never touches the database ─────────────────


async def test_legacy_key_is_admin_and_never_queries(keyed) -> None:
    session = _KeySession()
    principal, request = await _resolve(LEGACY, session=session)
    assert principal == access.LEGACY_PRINCIPAL
    assert session.calls == [] and session.rollbacks == 0
    assert resolve_request_owner_id(request) == DEFAULT_OWNER_ID


def test_legacy_key_through_the_app_runs_no_lookup(keyed, session) -> None:
    client = TestClient(app, headers={"x-api-key": LEGACY})
    # /api/v2/streams/{id} with a malformed id is a 422 decided after auth.
    assert client.get("/api/v2/streams/not-a-uuid").status_code == 422
    assert session.calls == []


async def test_wrong_key_still_401_when_keyed(keyed) -> None:
    with pytest.raises(HTTPException) as exc:
        await _resolve("nobody")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid API key"


async def test_unknown_key_still_passes_open_mode_as_default_owner(open_mode) -> None:
    principal, request = await _resolve("nobody")
    assert principal == access.LEGACY_PRINCIPAL
    assert resolve_request_owner_id(request) == DEFAULT_OWNER_ID


def test_direct_call_without_request_keeps_pre_029_semantics(keyed) -> None:
    assert deps.verify_api_key(x_api_key=LEGACY) is None
    with pytest.raises(HTTPException):
        deps.verify_api_key(x_api_key="nobody")


def test_non_ascii_key_is_401_not_500(keyed) -> None:
    with pytest.raises(HTTPException) as exc:
        deps.verify_api_key(x_api_key="clé")
    assert exc.value.status_code == 401


# ─── participant keys ──────────────────────────────────────────────────


async def test_ingest_key_resolves_to_its_owner(keyed) -> None:
    principal, request = await _resolve("alice-ingest", method="POST", path="/api/apple/batch")
    assert principal is not None and principal.scope == "ingest"
    assert principal.owner_id == ALICE_OWNER
    assert resolve_request_owner_id(request) == ALICE_OWNER


async def test_participant_key_ignores_x_user_id(keyed, monkeypatch) -> None:
    monkeypatch.setattr("server.ingestion.owner.ALLOW_MULTI_USER", True)
    _, request = await _resolve("alice-ingest", method="POST", path="/api/apple/batch")
    request.headers["x-user-id"] = str(uuid4())
    assert resolve_request_owner_id(request) == ALICE_OWNER


async def test_participant_keys_work_in_open_mode_too(open_mode) -> None:
    principal, _ = await _resolve("alice-ingest", method="POST", path="/api/v2/apple/batch")
    assert principal is not None and principal.owner_id == ALICE_OWNER


async def test_lookup_rolls_the_session_back_before_the_route_runs(keyed) -> None:
    session = _KeySession()
    await _resolve("alice-ingest", session=session)
    assert session.rollbacks == 1


@pytest.mark.parametrize("mode", ["keyed", "open_mode"])
async def test_revoked_key_is_401_in_every_mode(mode, request) -> None:
    request.getfixturevalue(mode)
    with pytest.raises(HTTPException) as exc:
        await _resolve("bob-revoked", method="POST", path="/api/apple/batch")
    assert exc.value.status_code == 401
    assert exc.value.detail == "api_key_revoked"


async def test_lookup_failure_is_503_when_keyed(keyed) -> None:
    with pytest.raises(HTTPException) as exc:
        await _resolve("alice-ingest", session=_KeySession(fail=True))
    assert exc.value.status_code == 503


async def test_lookup_failure_keeps_the_open_pass_in_open_mode(open_mode) -> None:
    principal, _ = await _resolve("alice-ingest", session=_KeySession(fail=True))
    assert principal == access.LEGACY_PRINCIPAL


async def test_admin_key_from_the_table_acts_like_the_legacy_key(keyed) -> None:
    principal, request = await _resolve("coach-admin", method="POST", path="/api/v2/moments")
    assert principal is not None and principal.scope == "admin" and not principal.bound
    assert resolve_request_owner_id(request) == DEFAULT_OWNER_ID


# ─── scopes ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v2/series"),
        ("GET", "/api/v2/insights/latest"),
        ("POST", "/api/v2/moments"),
        ("GET", "/api/v2/owners"),
        ("GET", "/api/v2/sync/coverage"),
    ],
)
async def test_ingest_key_is_403_off_the_phone_surface(keyed, method, path) -> None:
    with pytest.raises(HTTPException) as exc:
        await _resolve("alice-ingest", method=method, path=path)
    assert exc.value.status_code == 403


@pytest.mark.parametrize(("method", "path"), sorted(PHONE_ROUTES))
async def test_ingest_key_reaches_every_phone_route(keyed, method, path) -> None:
    principal, _ = await _resolve("alice-ingest", method=method, path=path)
    assert principal is not None and principal.owner_id == ALICE_OWNER


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", "/api/v2/series", True),
        ("GET", "/api/v2/export", True),
        ("GET", "/api/apple/status", True),
        ("GET", "/api/v2/sync/runs/latest", True),
        ("POST", "/api/apple/batch", False),
        ("PUT", "/api/v2/sync/runs/{sync_run_id}/summary", False),
        ("GET", "/api/v2/insights/latest", False),
        ("GET", "/api/v2/receipts", False),
        ("POST", "/api/v2/moments", False),
    ],
)
async def test_read_key_reads_owner_scoped_routes_only(keyed, method, path, allowed) -> None:
    if allowed:
        principal, _ = await _resolve("alice-read", method=method, path=path)
        assert principal is not None and principal.scope == "read"
    else:
        with pytest.raises(HTTPException) as exc:
            await _resolve("alice-read", method=method, path=path)
        assert exc.value.status_code == 403


def test_unclassified_routes_are_admin_only() -> None:
    participant = Principal(scope="read", owner_id=ALICE_OWNER)
    assert route_class("GET", "/api/v2/some-route-added-later") == "admin"
    assert not is_allowed(participant, "GET", "/api/v2/some-route-added-later")
    assert is_allowed(access.LEGACY_PRINCIPAL, "DELETE", "/api/v2/anything")


def test_route_tables_name_real_routes() -> None:
    registered = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    missing = (PHONE_ROUTES | OWNER_READ_ROUTES) - registered
    assert not missing, f"access tables name routes the app does not serve: {sorted(missing)}"


def test_403_comes_from_the_live_app(keyed, session) -> None:
    client = TestClient(app, headers={"x-api-key": "alice-ingest"})
    response = client.get("/api/v2/insights/latest")
    assert response.status_code == 403
    assert response.json()["detail"].startswith("api_key_scope:")
    assert session.rollbacks == 1


def test_revoked_401_comes_from_the_live_app(keyed, session) -> None:
    client = TestClient(app, headers={"x-api-key": "bob-revoked"})
    assert client.post("/api/apple/batch", json={}).status_code == 401
