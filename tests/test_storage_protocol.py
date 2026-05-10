"""Verify the IngestStorage / AuditLog protocol seam.

Three concerns:
  * The default Postgres backend implements both protocols and behaves
    identically to the pre-protocol code path (no regression).
  * A test backend without an audit log can swap in via app.state and
    the route gracefully skips audit calls (covers the InfluxDB shape:
    append-only, no UPDATE).
  * X-User-Id propagates through the seam regardless of which backend
    is plugged in.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from server.ingestion.storage import (  # noqa: E402
    AuditLog,
    IngestStorage,
    PostgresAuditLog,
    PostgresIngestStorage,
    default_audit_log,
    default_storage,
)
from tests.test_api_contract import FakeRequest, FakeSession  # noqa: E402


def test_postgres_ingest_storage_implements_protocol():
    assert isinstance(PostgresIngestStorage(), IngestStorage)


def test_postgres_audit_log_implements_protocol():
    assert isinstance(PostgresAuditLog(), AuditLog)


def test_module_defaults_are_postgres():
    assert isinstance(default_storage, PostgresIngestStorage)
    assert isinstance(default_audit_log, PostgresAuditLog)


@pytest.mark.asyncio
async def test_route_uses_module_default_when_app_state_absent():
    """FakeRequest doesn't carry an app — the route must fall back to defaults."""
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"}],
        }
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1


class _RecordingStorage:
    """Storage-only test backend (no audit log)."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def get_or_create_device(self, session, device_type):
        self.calls.append(("device", device_type))
        return 1

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        self.calls.append(("ingest", metric, len(samples), str(owner_id)))
        return len(samples)


class _RecordingAuditLog:
    def __init__(self):
        self.calls: list[tuple] = []

    async def log_raw(self, session, device_id, raw_payload):
        self.calls.append(("log_raw", device_id))
        return 99

    async def mark_processed(self, session, raw_log_id):
        self.calls.append(("mark_processed", raw_log_id))


def _app_with(state_attrs: dict):
    """Build a fake `request.app` whose `.state` has the given attributes."""
    state = type("State", (), state_attrs)()
    return type("App", (), {"state": state})()


@pytest.mark.asyncio
async def test_route_dispatches_through_app_state_storage_and_audit():
    storage = _RecordingStorage()
    audit = _RecordingAuditLog()
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [
                {"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"},
                {"date": "2026-04-10T12:00:01Z", "qty": 73, "source": "Apple Watch"},
            ],
        }
    )
    request.app = _app_with({"storage": storage, "audit_log": audit})

    result = await server.apple_batch(request, session)

    assert result["records"] == 2
    storage_kinds = [c[0] for c in storage.calls]
    audit_kinds = [c[0] for c in audit.calls]
    assert storage_kinds == ["device", "ingest"]
    assert audit_kinds == ["log_raw", "mark_processed"]


@pytest.mark.asyncio
async def test_route_skips_audit_when_backend_does_not_provide_one():
    """InfluxDB-shape: storage present, audit_log explicitly None."""
    storage = _RecordingStorage()
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"}],
        }
    )
    request.app = _app_with({"storage": storage, "audit_log": None})

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    # Storage still got the writes…
    assert any(c[0] == "ingest" for c in storage.calls)
    # …but no SQL audit-log INSERT/UPDATE was issued against the session.
    raw_inserts = [c for c in session.calls if "raw_ingestion_log" in c[0]]
    assert raw_inserts == []


@pytest.mark.asyncio
async def test_empty_batch_skips_audit_when_no_audit_backend():
    storage = _RecordingStorage()
    session = FakeSession()
    request = FakeRequest({"metric": "heart_rate", "samples": []})
    request.app = _app_with({"storage": storage, "audit_log": None})

    result = await server.apple_batch(request, session)

    assert result["status"] == "empty"
    raw_inserts = [c for c in session.calls if "raw_ingestion_log" in c[0]]
    assert raw_inserts == []


@pytest.mark.asyncio
async def test_swappable_storage_receives_resolved_owner_id():
    storage = _RecordingStorage()
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"}],
        },
        headers={"x-user-id": "11111111-2222-3333-4444-555555555555"},
    )
    request.app = _app_with({"storage": storage, "audit_log": None})

    await server.apple_batch(request, session)

    ingest_call = next(c for c in storage.calls if c[0] == "ingest")
    assert UUID(ingest_call[3]) == UUID("11111111-2222-3333-4444-555555555555")


def test_recording_backends_satisfy_their_protocols():
    """Smoke check that the test doubles match the protocols (Liskov)."""
    assert isinstance(_RecordingStorage(), IngestStorage)
    assert isinstance(_RecordingAuditLog(), AuditLog)
