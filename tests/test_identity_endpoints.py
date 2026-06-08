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

NOW = datetime(2026, 6, 9, 8, 0, 0, tzinfo=UTC)
SID = UUID("5fd4a041-f371-51be-8b1e-8d6275534c60")
_STREAM = {
    "id": SID,
    "source_plugin_id": "apple-healthkit-ios",
    "origin_key": "apple watch",
    "device_label": "Apple Watch",
    "first_seen_at": NOW,
    "last_seen_at": NOW,
}


@pytest.fixture
def client(monkeypatch):
    async def fake_session():
        yield object()

    async def list_sources(_session, _owner):
        return [
            {
                "id": UUID("a26bf104-aa3a-5686-a87b-510ffeee3e94"),
                "plugin_id": "apple-healthkit-ios",
                "display_name": "apple-healthkit-ios",
                "first_seen_at": NOW,
                "last_seen_at": NOW,
            }
        ]

    async def list_streams(_session, _owner):
        return [_STREAM]

    async def list_devices(_session, _owner):
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
    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app) as c:
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
