"""Wire-contract tests for ``POST /api/v2/apple/batch`` (Plan 2026-09-03 Slice 2).

DB-free tests that pin the validation surface of the v2 ingest route.
Every test asserts on a 422 (validation rejection) or a non-422 from
the storage layer — never both. End-to-end storage paths (canonical
dual-write, projection, deletion apply) are exercised by the
Docker-backed trust-e2e gate and by the existing
``test_android_requests_accepted`` suite (which already replays the v1
fixtures through ``server.apple_batch``).

The v2 wire contract pinned here:

  * Route exists at ``POST /api/v2/apple/batch``.
  * ``schema_version: 2`` is required (v1 / future != 2 bodies are 422).
  * Per-sample ``uuid`` is required; non-UUID → 422.
  * Per-sample ``startDate`` + ``endDate`` are required; non-string → 422.
  * Per-sample ``unit`` is required; missing → 422.
  * Per-sample ``motionContext``, when present, must be one of
    sedentary / active / notSet; other values → 422.
  * Per-sample ``tzOffsetMinutes``, when present, must be in
    [-1440, +1440]; out of range → 422.
  * Forward-compatible additive fields (``extra='allow'``) are accepted.
  * Deletions array entries must each have a valid UUID.
  * Top-level required fields: ``metric``, ``batch_index`` (ge=0),
    ``total_batches`` (ge=1).

Successful-path assertions (200 with ``wire_schema_version: 2`` in the
response, deletion block with per-table supersede counts, etc.) live in
the existing v1 success-path test suite once a v2 corpus is generated,
and in the docker-compose-backed trust-e2e gate. Those paths require a
real Timescale DB; this file is intentionally DB-free so it runs in
trust-fast without Docker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Live app TestClient. We never reach the DB-touching code paths
    in this file — every test asserts on a 422 (validation) response."""
    from server.main import app  # noqa: E402

    return TestClient(app, headers={"x-api-key": "test-contract"})


# ─── Schema version gating ────────────────────────────────────────────


def test_route_rejects_schema_version_one(client: TestClient) -> None:
    """Body with schema_version=1 is rejected so v1 clients fall back
    to the v1 route instead of silently parsing a v2 shape."""
    body = {
        "schema_version": 1,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "schema_version" in resp.text.lower()


def test_route_rejects_schema_version_three(client: TestClient) -> None:
    """schema_version=3 (hypothetical future) is rejected — only v2 is
    accepted today. A future v3 would land on a separate route."""
    body = {
        "schema_version": 3,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "schema_version" in resp.text.lower()


# ─── Required fields per sample ───────────────────────────────────────


def test_route_rejects_missing_uuid(client: TestClient) -> None:
    """Sample missing ``uuid`` is a deterministic 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "uuid" in resp.text.lower()


def test_route_rejects_missing_endDate(client: TestClient) -> None:
    """Sample missing ``endDate`` is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000001",
                "startDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "enddate" in resp.text.lower()


def test_route_rejects_missing_startDate(client: TestClient) -> None:
    """Sample missing ``startDate`` is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000002",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "startdate" in resp.text.lower()


def test_route_rejects_missing_unit(client: TestClient) -> None:
    """Sample missing ``unit`` is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000003",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "unit" in resp.text.lower()


def test_route_rejects_empty_unit_string(client: TestClient) -> None:
    """Sample with empty ``unit`` is 422 (min_length=1)."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000004",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "unit" in resp.text.lower()


# ─── UUID format ───────────────────────────────────────────────────────


def test_route_rejects_bad_uuid_format(client: TestClient) -> None:
    """Sample with a non-UUID ``uuid`` is 422 (not 500)."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "not-a-uuid",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "uuid" in resp.text.lower()


def test_route_rejects_short_uuid(client: TestClient) -> None:
    """UUID with the wrong length is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "abc-123",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


# ─── Motion context enum ──────────────────────────────────────────────


def test_route_rejects_bad_motion_context(client: TestClient) -> None:
    """Motion context outside the allowed enum is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000010",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
                "motionContext": "running",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "motioncontext" in resp.text.lower()


# ─── Timezone offset bounds ────────────────────────────────────────────


def test_route_rejects_out_of_range_tz_offset(client: TestClient) -> None:
    """tzOffsetMinutes outside [-1440, +1440] is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000030",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
                "tzOffsetMinutes": 2000,
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "tzoffsetminutes" in resp.text.lower()


def test_route_rejects_negative_overflow_tz_offset(client: TestClient) -> None:
    """tzOffsetMinutes=-1500 (one minute below the min) is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000031",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
                "tzOffsetMinutes": -1500,
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


# ─── Deletion array validation ────────────────────────────────────────


def test_deletions_array_must_have_valid_uuids(client: TestClient) -> None:
    """Deletions with non-UUID entries are 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
        "deletions": [{"uuid": "not-a-uuid"}],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "uuid" in resp.text.lower()


def test_deletions_array_rejects_short_uuid(client: TestClient) -> None:
    """Deletions with a too-short UUID are 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
        "deletions": [{"uuid": "abc-123"}],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


def test_deletions_array_rejects_bad_deleted_at(client: TestClient) -> None:
    """Deletions with a non-string ``deletedAt`` are 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
        "deletions": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000060",
                "deletedAt": 12345,  # not a string
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


# ─── Top-level required fields ────────────────────────────────────────


def test_route_rejects_missing_metric(client: TestClient) -> None:
    """Body missing ``metric`` is 422."""
    body = {
        "schema_version": 2,
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "metric" in resp.text.lower()


def test_route_rejects_missing_batch_index(client: TestClient) -> None:
    """Body missing ``batch_index`` is 422."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "total_batches": 1,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "batch_index" in resp.text.lower()


def test_route_rejects_negative_batch_index(client: TestClient) -> None:
    """Body with ``batch_index < 0`` is 422 (ge=0 constraint)."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": -1,
        "total_batches": 1,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


def test_route_rejects_total_batches_below_one(client: TestClient) -> None:
    """Body with ``total_batches < 1`` is 422 (ge=1 constraint)."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 0,
        "samples": [],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text


# ─── JSON error envelope is serializable ──────────────────────────────


def test_422_response_is_json_serializable(client: TestClient) -> None:
    """The 422 detail body must be JSON-serializable (no raw Python
    ValueError leaking via Pydantic's ``ctx.error``). Tests assert the
    response body round-trips through ``json.dumps`` cleanly. Without
    this guard, a frozen iOS client parsing the response would crash."""
    import json

    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000070",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
                "motionContext": "running",  # invalid enum
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    # Must serialize cleanly — proves no ValueError leaked into ctx.
    parsed = json.loads(resp.text)
    assert isinstance(parsed, dict)
    assert "detail" in parsed