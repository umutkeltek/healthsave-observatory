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
  * Identity gate: anchored samples (``startDate``/``start`` present)
    must carry ``uuid``; uuid-bearing samples must carry an interval;
    anchored samples must carry both bounds. Missing → 422.
  * Unit gate: quantity samples (``qty`` present) for ontology-known
    metrics must declare ``unit`` in the metric's allowed-units set
    (HealthKit ``unitString`` spellings included); unknown unit → 422.
  * Field FORMAT stays envelope-level: non-UUID uuid, empty unit/source,
    bad motionContext enum, out-of-range tzOffsetMinutes → 422.
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

def test_deletions_array_extra_keys_accepted() -> None:
    """V2Deletion uses ``extra='allow'`` so a future client-stamped
    observation timestamp (or any other key) parses cleanly. The route
    keeps only the typed ``uuid`` for supersede semantics; extras are
    dropped silently (the JSON Schema will reflect that after the
    follow-up ``make regen-v2-schemas`` in Slice 7). Replaces the
    older ``deletedAt`` test that pinned a typed field we never
    promised — the oracle review (2026-09-04) flagged it as a name
    that implied a client-stamped timestamp we never asserted.

    DB-free / validation-layer only: the route will not progress past
    ``_write_canonical_observations`` without a real DB (the local env
    has none), but the validation pass must succeed.
    """
    from server.api.v2_apple_batch import V2AppleBatchPayload
    V2AppleBatchPayload.model_validate(
        {
            "schema_version": 2,
            "metric": "heart_rate",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [],
            "deletions": [
                {
                    "uuid": "d2c70000-0000-4000-8000-000000000060",
                    "deletionObservedAt": "2026-09-01T07:14:00Z",
                    "locale": "en_US",
                }
            ],
        }
    )


def test_deletion_convergence_two_payloads_parse_identically() -> None:
    """Plan 2026-09-03 Slice 7 (oracle follow-up): the same deletion
    uuid sent in two consecutive v2 batches parses identically and
    extracts the same uuid for the supersede pass. The DB-layer
    idempotency guarantee (``mark_*_superseded`` rowcount=0 on the
    second call) lives in the storage suite + the e2e test, not here.
    Pinned here at the validation layer so the wire shape can't regress
    in a way that breaks the storage contract."""
    from server.api.v2_apple_batch import V2AppleBatchPayload
    payload = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [],
        "deletions": [{"uuid": "d2c70000-0000-4000-8000-0000000000a1"}],
    }
    first = V2AppleBatchPayload.model_validate(payload)
    second = V2AppleBatchPayload.model_validate(payload)
    assert len(first.deletions) == 1
    assert len(second.deletions) == 1
    assert first.deletions[0].uuid == second.deletions[0].uuid


def test_no_deletions_field_is_accepted() -> None:
    """A v2 batch with no ``deletions`` key parses cleanly — this is the
    common case for anchored queries that reported no HKDeletedObject on
    this delivery. Pinned because the prior ``deletedAt`` test masked
    the no-deletions path; oracle review flagged deletion-only pages as
    a data-loss risk that the test suite had not pinned either way.
    """
    from server.api.v2_apple_batch import V2AppleBatchPayload
    payload = V2AppleBatchPayload.model_validate(
        {
            "schema_version": 2,
            "metric": "heart_rate",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [],
        }
    )
    assert payload.deletions == []


def test_deletions_field_empty_list_is_accepted() -> None:
    """An explicit ``deletions: []`` also parses cleanly — alternative
    spelling the iOS test seam uses. Belt-and-braces with the no-field
    test above."""
    from server.api.v2_apple_batch import V2AppleBatchPayload
    payload = V2AppleBatchPayload.model_validate(
        {
            "schema_version": 2,
            "metric": "heart_rate",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [],
            "deletions": [],
        }
    )
    assert payload.deletions == []


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


# ─── Metric-keyed unit gate (Eric's ask #3) ───────────────────────────


def test_route_rejects_unit_outside_metric_allowed_units(client: TestClient) -> None:
    """A unit the metric's ontology does not allow is a deterministic
    422 — "a server that guesses a unit corrupts data silently, so ours
    refuses instead" (Eric). Empty or missing unit would corrupt the
    same way; the gate is per-metric, driven by ``allowed_units``."""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000080",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "furlongs/fortnight",
                "source": "Apple Watch",
            }
        ],
    }
    resp = client.post("/api/v2/apple/batch", json=body)
    assert resp.status_code == 422, resp.text
    assert "unit" in resp.text.lower()


def test_route_rejects_quantity_sample_without_unit(client: TestClient) -> None:
    """An anchored qty-bearing sample for an ontology-known quantity
    metric must declare its unit — omitting it is the silent-guess Eric
    refused. (Date-only HKStatistics aggregates are exempt — exact
    canonical-unit fallback by construction.)"""
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000081",
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


def test_unit_gate_accepts_canonical_and_healthkit_spellings() -> None:
    """Both the ontology's canonical spelling and the HealthKit
    ``unitString`` spellings pass the gate (DB-free, model-level).
    Pinning acceptance matters as much as rejection: a gate that only
    knew the canonical spelling would wedge every frozen client, whose
    unit strings come straight from HKUnit.unitString."""
    from server.api.v2_apple_batch import V2AppleBatchPayload

    base = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
    }
    sample = {
        "uuid": "d2c70000-0000-4000-8000-000000000082",
        "startDate": "2026-08-30T07:14:00-04:00",
        "endDate": "2026-08-30T07:14:00-04:00",
        "qty": 72,
        "source": "Apple Watch",
    }
    for unit in ("bpm", "count/min"):
        payload = V2AppleBatchPayload.model_validate(
            {**base, "samples": [{**sample, "unit": unit}]}
        )
        assert payload.samples[0].unit == unit

    # A different metric with its own spellings validates independently:
    # the gate is metric-keyed, not a global unit list.
    vo2 = V2AppleBatchPayload.model_validate(
        {
            **base,
            "metric": "vo2_max",
            "samples": [
                {
                    "uuid": "d2c70000-0000-4000-8000-000000000083",
                    "startDate": "2026-08-30T07:14:00-04:00",
                    "endDate": "2026-08-30T07:14:00-04:00",
                    "qty": 52.1,
                    "unit": "ml/kg*min",
                    "source": "Apple Watch",
                }
            ],
        }
    )
    assert vo2.samples[0].unit == "ml/kg*min"


def test_unit_gate_ignores_unmapped_metrics() -> None:
    """Wire metrics the ontology does not know stay lenient at the unit
    gate — parity with ``normalize_apple_batch``, which rejects them
    per-sample (``unmapped_metric``) rather than wedging the batch."""
    from server.api.v2_apple_batch import V2AppleBatchPayload

    payload = V2AppleBatchPayload.model_validate(
        {
            "schema_version": 2,
            "metric": "some_future_metric",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [
                {
                    "uuid": "d2c70000-0000-4000-8000-000000000084",
                    "startDate": "2026-08-30T07:14:00-04:00",
                    "endDate": "2026-08-30T07:14:00-04:00",
                    "qty": 1,
                    "unit": "anything",
                    "source": "Apple Watch",
                }
            ],
        }
    )
    assert payload.samples[0].unit == "anything"


# ─── Metric-keyed identity gate (Eric's ask #6) ───────────────────────


def test_identity_gate_requires_uuid_on_anchored_samples() -> None:
    """An anchored sample (startDate/start present) without its
    HKSample UUID cannot be superseded by a later delete+reinsert —
    the whole point of the v2 identity — so it is a deterministic 422."""
    from pydantic import ValidationError

    from server.api.v2_apple_batch import V2AppleBatchPayload

    with pytest.raises(ValidationError, match="uuid"):
        V2AppleBatchPayload.model_validate(
            {
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
        )


def test_identity_gate_requires_interval_on_uuid_samples() -> None:
    """A UUID with no interval is unmatchable — reject at the gate."""
    from pydantic import ValidationError

    from server.api.v2_apple_batch import V2AppleBatchPayload

    with pytest.raises(ValidationError, match="startDate"):
        V2AppleBatchPayload.model_validate(
            {
                "schema_version": 2,
                "metric": "heart_rate",
                "batch_index": 0,
                "total_batches": 1,
                "samples": [
                    {
                        "uuid": "d2c70000-0000-4000-8000-000000000085",
                        "qty": 72,
                        "unit": "count/min",
                        "source": "Apple Watch",
                    }
                ],
            }
        )


def test_identity_gate_requires_end_bound_on_anchored_samples() -> None:
    """Eric's ask #1: without the end bound a RHR revision cannot be
    told from a duplicate. An anchored sample missing endDate is 422."""
    from pydantic import ValidationError

    from server.api.v2_apple_batch import V2AppleBatchPayload

    with pytest.raises(ValidationError, match="endDate"):
        V2AppleBatchPayload.model_validate(
            {
                "schema_version": 2,
                "metric": "heart_rate",
                "batch_index": 0,
                "total_batches": 1,
                "samples": [
                    {
                        "uuid": "d2c70000-0000-4000-8000-000000000086",
                        "startDate": "2026-08-30T07:14:00-04:00",
                        "qty": 72,
                        "unit": "count/min",
                        "source": "Apple Watch",
                    }
                ],
            }
        )


# ─── Family-aware envelope acceptance (the wedge guard) ───────────────


def test_envelope_accepts_all_ios_emission_families() -> None:
    """The committed iOS app emits eight sample families and only
    anchored quantity carries the full identity set. Pinning that one
    shape on every family 422'd the rest deterministically — a Law-6
    wedge for frozen clients. This test is the guard: every real
    family shape parses at the envelope."""
    from server.api.v2_apple_batch import V2AppleBatchPayload

    families = {
        # anchored quantity (the full identity set)
        "heart_rate": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000090",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 72,
                "unit": "count/min",
                "source": "Apple Watch",
                "tzOffsetMinutes": -240,
                "motionContext": "sedentary",
            }
        ],
        # HKStatistics daily aggregate: date + qty, no uuid/unit
        "step_count": [
            {"date": "2026-08-30T00:00:00Z", "qty": 8500, "source": "HealthKit Statistics"}
        ],
        # workout: uuid + start/end/duration (HKWorkout is an HKSample;
        # the identity gate requires the uuid on anchored samples)
        "workouts": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000095",
                "name": "Running",
                "start": "2026-08-30T07:00:00-04:00",
                "end": "2026-08-30T07:30:00-04:00",
                "duration": 1800,
                "source": "Apple Watch",
                "activeEnergy": 200.0,
                "distance": 5000.0,
            }
        ],
        # sleep stage: uuid + interval + categorical value, no qty/unit
        "sleep_analysis": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000091",
                "startDate": "2026-08-30T23:00:00-04:00",
                "endDate": "2026-08-30T23:45:00-04:00",
                "value": "HKCategoryValueSleepAnalysisInBed",
                "source": "Apple Watch",
                "tzOffsetMinutes": -240,
            }
        ],
        # ECG: uuid + interval + classification, no qty/unit
        "ecg": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000092",
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:30-04:00",
                "start": "2026-08-30T07:14:00-04:00",
                "end": "2026-08-30T07:14:30-04:00",
                "classification": "sinusRhythm",
                "numberOfVoltageMeasurements": 1000,
                "samplingFrequency": 512.0,
                "source": "Apple Watch",
            }
        ],
        # medication dose event: uuid + date + status/name, no qty/unit
        "medication_dose_event": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000093",
                "startDate": "2026-08-30T08:00:00-04:00",
                "endDate": "2026-08-30T08:00:00-04:00",
                "date": "2026-08-30T08:00:00-04:00",
                "medication_status": "completed",
                "medication_name": "Aspirin",
                "medication_unit": "mg",
                "source": "Apple Watch",
            }
        ],
        # category event: uuid + interval + qty, no unit
        "category_menstrual_flow": [
            {
                "uuid": "d2c70000-0000-4000-8000-000000000094",
                "startDate": "2026-08-30T08:00:00-04:00",
                "endDate": "2026-08-30T09:00:00-04:00",
                "date": "2026-08-30T08:00:00-04:00",
                "qty": 1.0,
                "source": "Apple Watch",
                "rawValue": 1,
            }
        ],
        # activity summary: date + ring fields, no identity keys at all
        "activity_summaries": [
            {
                "date": "2026-08-30T00:00:00Z",
                "activeEnergyBurned": 400.0,
                "activeEnergyBurnedGoal": 500.0,
                "appleExerciseTime": 30.0,
                "appleExerciseTimeGoal": 30.0,
                "appleStandHours": 10.0,
                "appleStandHoursGoal": 12.0,
            }
        ],
    }
    for metric, samples in families.items():
        payload = V2AppleBatchPayload.model_validate(
            {
                "schema_version": 2,
                "metric": metric,
                "batch_index": 0,
                "total_batches": 1,
                "samples": samples,
            }
        )
        assert len(payload.samples) == 1, f"{metric} lost a sample at the envelope"
    assert len(families) == 8, "guard every family iOS emits — add new ones here"


# ─── iOS serializer → server round-trip (Slice 7 oracle follow-up) ───
#
# The oracle review (2026-09-04) flagged: "a handwritten Swift fixture
# that happens to resemble a handwritten JSON Schema proves little.
# The useful test is serializer output → v2 schema/server parser →
# storage." This test takes the exact JSON shape the committed iOS
# ``AppleSyncBatchPayload.jsonData()`` serializer emits in
# ``ios_app/Tests/HealthSyncTests/V2PayloadShapeTests/testV2PayloadSerializesToValidJSON``
# and asserts every field Eric's engine relies on survives the
# server's wire-model parse. A model-field rename on either side
# that doesn't match will fail here, even if both sides agree on a
# wrong key.


IOS_PAYLOAD_SERIALIZER_FIXTURE = {
    "schema_version": 2,
    "metric": "heart_rate",
    "batch_index": 2,
    "total_batches": 5,
    "samples": [
        {
            "uuid": "D2C70000-0000-4000-8000-000000000001",
            "startDate": "2026-08-30T07:14:00-04:00",
            "endDate": "2026-08-30T07:14:00-04:00",
            "qty": 52,
            "unit": "count/min",
            "tzOffsetMinutes": -240,
            "motionContext": "sedentary",
            "source": "Apple Watch",
        }
    ],
    "deletions": [
        {"uuid": "D2C70000-0000-4000-8000-00000000007A"},
    ],
    "source_bundle_id": "com.healthsave.ios",
    "device": {"name": "Test iPhone", "model": "iPhone17,2"},
}


def test_ios_serializer_output_round_trips_through_v2_model() -> None:
    """The exact JSON shape iOS's ``AppleSyncBatchPayload.jsonData()``
    emits (verified by ``testV2PayloadSerializesToValidJSON``) must
    parse cleanly through the server's ``V2AppleBatchPayload``. Any
    field rename / type drift on either side that the other doesn't
    catch will fail here.
    """
    from server.api.v2_apple_batch import V2AppleBatchPayload
    payload = V2AppleBatchPayload.model_validate(IOS_PAYLOAD_SERIALIZER_FIXTURE)
    assert payload.schema_version == 2
    assert payload.metric == "heart_rate"
    assert payload.batch_index == 2
    assert payload.total_batches == 5
    assert payload.source_bundle_id == "com.healthsave.ios"
    assert payload.device is not None
    assert payload.device["model"] == "iPhone17,2"
    assert len(payload.samples) == 1
    assert len(payload.deletions) == 1
    sample = payload.samples[0]
    assert sample.uuid == "D2C70000-0000-4000-8000-000000000001"
    assert sample.startDate == "2026-08-30T07:14:00-04:00"
    assert sample.endDate == "2026-08-30T07:14:00-04:00"
    assert sample.qty == 52
    assert sample.unit == "count/min"
    assert sample.tzOffsetMinutes == -240
    assert sample.motionContext == "sedentary"
    assert sample.source == "Apple Watch"
    assert payload.deletions[0].uuid == "D2C70000-0000-4000-8000-00000000007A"


def test_ios_serializer_output_satisfies_generated_json_schema() -> None:
    """Cross-check the iOS-emitted JSON against the generated
    ``contracts/json-schema/V2AppleBatchPayload.json``. ``jsonschema``
    is optional (the lock-file gate does not require it); if absent,
    skip with a clear message — the model-validation test above is the
    load-bearing gate."""
    import importlib.util as _ilu
    jsonschema_spec = _ilu.find_spec("jsonschema")
    if jsonschema_spec is None:
        pytest.skip("jsonschema not installed; model-validation test covers the contract")
    import json
    import jsonschema as _js  # type: ignore[import-not-found]
    from pathlib import Path
    schema_path = Path(__file__).resolve().parents[3] / "contracts" / "json-schema" / "V2AppleBatchPayload.json"
    schema = json.loads(schema_path.read_text())
    _js.validate(IOS_PAYLOAD_SERIALIZER_FIXTURE, schema)
