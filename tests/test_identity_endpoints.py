"""R2 Track A — v2 Source/Device/Stream read endpoints (no-DB contract test).

Mirrors the existing TestClient + dependency-override pattern: the registry repo
is monkeypatched so the routes are exercised without a database, validating
response-model shaping, the typed contract, and the 404 path. The real DB path is
covered by the local/e2e ingest→registry→endpoint run.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from server.api import v2_identity  # noqa: E402
from server.api.deps import get_session  # noqa: E402

from contracts import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID  # noqa: E402

NOW = datetime(2026, 6, 9, 8, 0, 0, tzinfo=UTC)
SID = UUID("5fd4a041-f371-51be-8b1e-8d6275534c60")
DIRECT_SID = UUID("3de17cc1-a369-5a9b-92ac-01c75e85d8dc")
RELAYED_SID = UUID("1a506ee4-3143-5bf0-a11e-4537f8c5635b")
_STREAM = {
    "id": SID,
    "source_plugin_id": "apple-healthkit-ios",
    "origin_key": "apple watch",
    "device_label": "Apple Watch",
    "first_seen_at": NOW,
    "last_seen_at": NOW,
}


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _LinkRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []
        self.find_calls: list[tuple[object, dict]] = []
        self.reconcile_calls: list[tuple[object, dict]] = []

    async def upsert_device_identity_link(self, session, **kwargs):
        self.calls.append((session, kwargs))

    async def find_session_candidate_pairs(self, session, **kwargs):
        self.find_calls.append((session, kwargs))
        return [_PAIR_ASSIGNED, _PAIR_REJECTED]

    async def reconcile_session_pair(self, session, **kwargs):
        self.reconcile_calls.append((session, kwargs))
        return _ReconciliationResult(assigned=kwargs["provider_subject_id"] == "polar-user-10579")


class _Pair:
    def __init__(self, *, provider_subject_id: str) -> None:
        self.provider_subject_id = provider_subject_id
        self.direct = object()
        self.relayed = object()
        self.device_link = object()


class _ReconciliationResult:
    def __init__(self, *, assigned: bool) -> None:
        self.assigned = assigned


_PAIR_ASSIGNED = _Pair(provider_subject_id="polar-user-10579")
_PAIR_REJECTED = _Pair(provider_subject_id="polar-user-rejected")


@pytest.fixture
def client(monkeypatch):
    session = _Session()
    link_repo = _LinkRepo()

    async def fake_session():
        yield session

    async def list_sources(_session, _owner, *, limit=None, offset=0):
        return [
            {
                "id": UUID("a26bf104-aa3a-5686-a87b-510ffeee3e94"),
                "plugin_id": "apple-healthkit-ios",
                "display_name": "apple-healthkit-ios",
                "first_seen_at": NOW,
                "last_seen_at": NOW,
            }
        ]

    async def list_streams(_session, _owner, *, limit=None, offset=0):
        return [_STREAM]

    async def list_devices(_session, _owner, *, limit=None, offset=0):
        return [
            {
                "device_label": "Apple Watch",
                "stream_count": 1,
                "first_seen_at": NOW,
                "last_seen_at": NOW,
            }
        ]

    async def get_stream(_session, _owner, stream_id):
        return _STREAM if stream_id == SID else None

    monkeypatch.setattr(v2_identity.registry, "list_sources", list_sources)
    monkeypatch.setattr(v2_identity.registry, "list_streams", list_streams)
    monkeypatch.setattr(v2_identity.registry, "list_devices", list_devices)
    monkeypatch.setattr(v2_identity.registry, "get_stream", get_stream)
    monkeypatch.setattr(v2_identity, "fusion_repository", link_repo, raising=False)
    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app) as c:
            c._identity_session = session
            c._identity_link_repo = link_repo
            yield c
    finally:
        server.app.dependency_overrides.clear()


def test_sources(client):
    r = client.get("/api/v2/sources")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["sources"][0]["plugin_id"] == "apple-healthkit-ios"


def test_streams(client):
    r = client.get("/api/v2/streams")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["streams"][0]["origin_key"] == "apple watch"
    assert body["streams"][0]["id"] == str(SID)


def test_devices(client):
    r = client.get("/api/v2/devices")
    assert r.status_code == 200
    assert r.json()["devices"][0]["device_label"] == "Apple Watch"


def test_get_stream_found_and_missing(client):
    ok = client.get(f"/api/v2/streams/{SID}")
    assert ok.status_code == 200
    assert ok.json()["origin_key"] == "apple watch"

    missing = client.get("/api/v2/streams/11111111-1111-1111-1111-111111111111")
    assert missing.status_code == 404


def test_create_confirmed_device_identity_link(client):
    response = client.post(
        "/api/v2/device-identity-links",
        json={
            "direct_stream_id": str(DIRECT_SID),
            "relayed_stream_id": str(RELAYED_SID),
            "confidence": "strong",
            "evidence": {
                "vendor_family": "polar",
                "provider_subject_id": "polar-user-10579",
                "reason": "operator confirmed same physical device",
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["direct_stream_id"] == str(DIRECT_SID)
    assert body["relayed_stream_id"] == str(RELAYED_SID)
    assert body["status"] == "confirmed"
    assert body["confidence"] == "strong"
    assert client._identity_session.commits == 1
    [(session, kwargs)] = client._identity_link_repo.calls
    assert session is client._identity_session
    assert kwargs["owner_id"] == DEFAULT_OWNER_ID
    assert kwargs["direct_stream_id"] == DIRECT_SID
    assert kwargs["relayed_stream_id"] == RELAYED_SID
    assert kwargs["status"] == "confirmed"
    assert kwargs["confidence"].value == "strong"
    assert kwargs["evidence"]["vendor_family"] == "polar"


def test_create_device_identity_link_rejects_weak_confidence(client):
    response = client.post(
        "/api/v2/device-identity-links",
        json={
            "direct_stream_id": str(DIRECT_SID),
            "relayed_stream_id": str(RELAYED_SID),
            "confidence": "weak",
            "evidence": {"reason": "not enough"},
        },
    )

    assert response.status_code == 422
    assert client._identity_link_repo.calls == []
    assert client._identity_session.commits == 0


def test_create_device_identity_link_rejects_same_stream(client):
    response = client.post(
        "/api/v2/device-identity-links",
        json={
            "direct_stream_id": str(DIRECT_SID),
            "relayed_stream_id": str(DIRECT_SID),
            "confidence": "strong",
            "evidence": {"reason": "bad request"},
        },
    )

    assert response.status_code == 422
    assert client._identity_link_repo.calls == []
    assert client._identity_session.commits == 0


def test_reconcile_device_identity_link_sessions(client):
    response = client.post("/api/v2/device-identity-links/session-reconciliations?limit=25")

    assert response.status_code == 201
    assert response.json() == {"matched_pairs": 2, "assigned": 1, "rejected": 1}
    [(session, find_kwargs)] = client._identity_link_repo.find_calls
    assert session is client._identity_session
    assert find_kwargs == {
        "owner_id": DEFAULT_OWNER_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": 25,
    }
    assert [call[0] for call in client._identity_link_repo.reconcile_calls] == [
        client._identity_session,
        client._identity_session,
    ]
    assert [
        call[1]["provider_subject_id"] for call in client._identity_link_repo.reconcile_calls
    ] == ["polar-user-10579", "polar-user-rejected"]
    assert all(
        call[1]["decided_by"] == "operator-api"
        for call in client._identity_link_repo.reconcile_calls
    )
    assert client._identity_session.commits == 1
