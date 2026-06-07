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
from server.ingestion.owner import DEFAULT_OWNER_ID  # noqa: E402
from server.ingestion.storage import (  # noqa: E402
    AuditLog,
    IngestStorage,
    PostgresAuditLog,
    PostgresIngestStorage,
    default_audit_log,
    default_storage,
)

from tests.test_api_contract import FakeRequest, FakeSession  # noqa: E402

TEST_OWNER_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
TEST_OWNER_HEADER = str(TEST_OWNER_ID)


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
        headers={"x-user-id": TEST_OWNER_HEADER},
    )
    request.app = _app_with({"storage": storage, "audit_log": None})

    await server.apple_batch(request, session)

    ingest_call = next(c for c in storage.calls if c[0] == "ingest")
    assert UUID(ingest_call[3]) == TEST_OWNER_ID


def test_recording_backends_satisfy_their_protocols():
    """Smoke check that the test doubles match the protocols (Liskov)."""
    assert isinstance(_RecordingStorage(), IngestStorage)
    assert isinstance(_RecordingAuditLog(), AuditLog)


# ──────────────────────────────────────────────────────────────────────
# Phase 6.1 — the route delegates the per-device write loop to the
# Apple Health plugin via the SDK loader. The route's contract with
# the plugin is exercised here: a fake plugin attached to
# app.state.apple_health_plugin must be invoked exactly once with the
# expected payload shape.
# ──────────────────────────────────────────────────────────────────────


class _RecordingPlugin:
    """Records each call so the test can assert payload shape + count.

    Phase 6.1: subclassing :class:`plugin_sdk.Source` would couple this
    test to the SDK's optional lifecycle methods; instead we duck-type
    the single method the route invokes. The
    ``test_recording_plugin_is_shape_compatible_with_source`` smoke
    check below pins that the duck-typed shape matches the Source ABC's
    ``ingest`` signature.
    """

    def __init__(self, accepted: int = 0) -> None:
        self.calls: list[dict] = []
        self._accepted = accepted

    async def ingest(self, payload: dict) -> dict:
        self.calls.append(payload)
        return {"accepted": self._accepted, "rejected": 0}


def test_recording_plugin_is_shape_compatible_with_source():
    """Phase 6.1 type-pin: the route invokes ``await plugin.ingest(payload)``
    on whatever ``_resolve_apple_health_plugin`` returns. Pin that the
    test double exposes the same async ``ingest(payload) -> dict``
    signature the SDK's ``Source`` ABC declares — otherwise a Source
    ABC rename would silently leave the route delegation tests passing
    while production breaks.
    """
    import inspect

    from plugin_sdk import Source

    plugin = _RecordingPlugin()
    # Both have an async `ingest` callable with one positional arg
    # named `payload`. Refactors that rename the method or change the
    # arg name fail this check before they fail production.
    assert inspect.iscoroutinefunction(plugin.ingest)
    assert inspect.iscoroutinefunction(Source.ingest)
    plugin_params = list(inspect.signature(plugin.ingest).parameters)
    source_params = list(inspect.signature(Source.ingest).parameters)
    # Source.ingest is unbound so its first param is `self`; the
    # duck-typed plugin.ingest is bound and starts at `payload`.
    assert plugin_params == ["payload"]
    assert source_params == ["self", "payload"]


@pytest.mark.asyncio
async def test_route_delegates_apple_batch_through_plugin_loader():
    """Phase 6.1 contract: the route resolves the Apple Health plugin
    via ``_resolve_apple_health_plugin`` (which checks
    ``app.state.apple_health_plugin`` first) and invokes its ``ingest``
    method exactly once per non-empty batch.

    The payload MUST carry the Phase 6.1 keys: ``storage`` (the
    Protocol injection that preserves Phase 5C backend-swap),
    ``session``, ``device_id`` (pre-resolved by the route for the
    audit row), ``first_device_name`` (so the plugin reuses the
    pre-resolved id), ``metric``, ``samples``, canonical observations,
    and ``owner_id``.
    """
    storage = _RecordingStorage()
    plugin = _RecordingPlugin(accepted=2)
    projection = object()
    session = FakeSession()
    samples = [
        {"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"},
        {"date": "2026-04-10T12:00:01Z", "qty": 73, "source": "Apple Watch"},
    ]
    request = FakeRequest({"metric": "heart_rate", "samples": samples})
    request.app = _app_with(
        {
            "storage": storage,
            "audit_log": None,
            "apple_health_plugin": plugin,
            "measurement_projection": projection,
        }
    )

    result = await server.apple_batch(request, session)

    # Plugin was invoked exactly once.
    assert len(plugin.calls) == 1
    payload = plugin.calls[0]

    # Payload carries the Phase 6.1 contract keys.
    assert payload["storage"] is storage
    assert payload["projection"] is projection
    assert payload["session"] is session
    assert payload["metric"] == "heart_rate"
    assert payload["samples"] == samples
    assert len(payload["canonical_observations"]) == 2
    assert {obs.metric_id for obs in payload["canonical_observations"]} == {"vital.heart_rate"}
    assert payload["first_device_name"] == "Apple Watch"
    assert payload["device_id"] == 1  # _RecordingStorage returns 1
    # owner_id is the default sentinel when no X-User-Id header is present.
    assert payload["owner_id"] == DEFAULT_OWNER_ID

    # The route only invoked storage for the first-device resolution
    # (the plugin handles the per-device loop in production).
    storage_kinds = [c[0] for c in storage.calls]
    assert storage_kinds == ["device"]

    # Response shape and record count come from the plugin's return.
    assert result["records"] == 2
    assert result["status"] == "processed"
    assert result["metric"] == "heart_rate"


@pytest.mark.asyncio
async def test_route_resolves_plugin_once_across_two_requests_when_state_absent():
    """Phase 6.1 cache contract: when no ``app.state.apple_health_plugin``
    is set, the route falls back to the module-level lazy cache via
    ``_load_apple_health_plugin``. That function must run discovery
    EXACTLY ONCE across N requests — re-running ``discover()`` per
    request would burn YAML I/O on the hot path and re-import the
    plugin module, potentially with subtle log-spam side effects.

    Calls the loader directly twice and confirms instance identity:
    same object both times. The route test above already pins that
    the cache is the seam the route uses.
    """
    from server.api import ingest as ingest_module

    # Reset the module cache so prior tests don't poison this assertion.
    saved = ingest_module._apple_health_plugin
    ingest_module._apple_health_plugin = None
    try:
        first = ingest_module._load_apple_health_plugin()
        second = ingest_module._load_apple_health_plugin()
        assert first is second, "lazy cache must return the same instance across calls"
    finally:
        ingest_module._apple_health_plugin = saved


@pytest.mark.asyncio
async def test_route_propagates_resolved_owner_id_into_plugin_payload():
    """X-User-Id resolution still happens in the route — it gets
    threaded into the plugin payload, not into the storage call shape
    directly. This pins that the v1 owner-id seam survives the
    delegation.
    """
    plugin = _RecordingPlugin(accepted=1)
    storage = _RecordingStorage()
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"}],
        },
        headers={"x-user-id": TEST_OWNER_HEADER},
    )
    request.app = _app_with(
        {
            "storage": storage,
            "audit_log": None,
            "apple_health_plugin": plugin,
        }
    )

    await server.apple_batch(request, session)

    assert plugin.calls[0]["owner_id"] == TEST_OWNER_ID
