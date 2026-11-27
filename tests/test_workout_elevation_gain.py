"""Workout elevation gain: wire ``elevationGain`` -> ``workouts.elevation_gain_m``.

The iPhone app (1.9.4 and later) sends a workout's total ascent in metres as
``elevationGain`` on a workouts sample, only when the watch recorded one. These
tests pin the server half of that agreement without a database:

- present on the wire -> stored; the snake_case alias works like its siblings;
- absent -> NULL on insert, and a re-sent workout without it keeps the stored
  value (the upsert COALESCEs);
- a value that is not a finite number >= 0 is dropped and the workout is kept,
  the way a bad ``distance`` is: never a rejected sample, never a 5xx;
- both batch routes accept it, the unchanged corpus fixture (an older app)
  ingests exactly as before, and the canonical ``workout.session`` record
  carries it.

The export side is pinned in ``tests/test_export_repository.py``; real-Postgres
proof (keep-on-resend, export round trip) lives in
``tests/e2e/test_workout_elevation_gain_e2e.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from contracts._base import Provenance  # noqa: E402
from normalization import normalize_apple_batch  # noqa: E402
from server.ingestion.handlers import _ingest_workouts  # noqa: E402

from tests.test_api_contract import FakeRequest, FakeResult, FakeSession  # noqa: E402

V1_FIXTURE = ROOT / "tests" / "fixtures" / "apple_healthsave" / "workout_batch.json"
V2_FIXTURE = ROOT / "tests" / "fixtures" / "apple_healthsave_v2" / "workouts_batch.json"


def _workout(**extra) -> dict:
    return {
        "name": "Hiking",
        "start": "2026-11-15T08:00:00.000Z",
        "end": "2026-11-15T10:30:00.000Z",
        "duration": 9000,
        "activeEnergy": 820,
        "distance": 11250,
        "source": "Apple Watch",
        **extra,
    }


async def _written_row(sample: dict) -> tuple[dict, str, object]:
    session = FakeSession()
    result = await _ingest_workouts(session, device_id=7, samples=[sample])
    [sql] = [sql for sql, _ in session.calls if "INSERT INTO workouts" in sql]
    row = session.insert_params_for("workouts")
    assert row is not None
    return row, sql, result


# ─── writer ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wire_elevation_gain_is_stored_in_metres() -> None:
    row, _, result = await _written_row(_workout(elevationGain=412.6))
    assert row["elevation_gain_m"] == 412.6
    assert row["distance_m"] == 11250.0
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_snake_case_alias_is_read_like_its_siblings() -> None:
    row, _, _ = await _written_row(_workout(elevation_gain_m=95))
    assert row["elevation_gain_m"] == 95.0


@pytest.mark.asyncio
async def test_a_recorded_flat_workout_keeps_its_zero() -> None:
    row, _, _ = await _written_row(_workout(elevationGain=0))
    assert row["elevation_gain_m"] == 0.0


@pytest.mark.asyncio
async def test_absent_field_inserts_null_and_a_resend_keeps_the_stored_value() -> None:
    row, sql, _ = await _written_row(_workout())
    assert row["elevation_gain_m"] is None
    # A NULL on the wire never erases what an earlier send stored.
    assert (
        "elevation_gain_m = COALESCE(EXCLUDED.elevation_gain_m, workouts.elevation_gain_m)" in sql
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        -1,
        -0.01,
        "steep",
        "",
        "1e400",
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        {"value": 10},
        [10],
        None,
    ],
    ids=repr,
)
async def test_unusable_value_is_dropped_and_the_workout_is_kept(bad) -> None:
    row, _, result = await _written_row(_workout(elevationGain=bad))
    assert row["elevation_gain_m"] is None
    # The rest of the workout is untouched and nothing counts as rejected.
    assert row["sport_type"] == "Hiking"
    assert row["distance_m"] == 11250.0
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_numeric_string_is_read_the_way_distance_is() -> None:
    row, _, _ = await _written_row(_workout(elevationGain="120.5", distance="11250"))
    assert row["elevation_gain_m"] == 120.5
    assert row["distance_m"] == 11250.0


# ─── v1 route (frozen POST /api/apple/batch) ───────────────────────────


@pytest.mark.asyncio
async def test_v1_route_stores_elevation_gain() -> None:
    session = FakeSession()
    payload = {"metric": "workouts", "samples": [_workout(elevationGain=412.6)]}

    result = await server.apple_batch(FakeRequest(payload), session)

    assert result["records"] == 1
    assert session.insert_params_for("workouts")["elevation_gain_m"] == 412.6


@pytest.mark.asyncio
async def test_v1_route_bad_value_is_not_an_error() -> None:
    session = FakeSession()
    payload = {"metric": "workouts", "samples": [_workout(elevationGain=-30)]}

    result = await server.apple_batch(FakeRequest(payload), session)

    assert result["records"] == 1
    assert session.insert_params_for("workouts")["elevation_gain_m"] is None
    assert session.committed is True


@pytest.mark.asyncio
async def test_unchanged_v1_fixture_ingests_exactly_as_before() -> None:
    """An app that never sends the field: same row, elevation NULL."""

    session = FakeSession()
    payload = json.loads(V1_FIXTURE.read_text())
    assert "elevationGain" not in json.dumps(payload)

    result = await server.apple_batch(FakeRequest(payload), session)

    assert result["records"] == 1
    row = session.insert_params_for("workouts")
    assert {k: row[k] for k in ("sport_type", "duration_ms", "calories", "distance_m")} == {
        "sport_type": "Running",
        "duration_ms": 2_700_000,
        "calories": 410.0,
        "distance_m": 7200.0,
    }
    assert (row["avg_hr"], row["max_hr"], row["source_id"]) == (142.0, 176.0, "Apple Watch")
    assert row["elevation_gain_m"] is None


# ─── v2 route (POST /api/v2/apple/batch) ───────────────────────────────


def _v2_session() -> FakeSession:
    """``FakeSession`` with the nested-transaction and supersede shape v2 needs."""

    class _RowcountResult(FakeResult):
        def __init__(self, rowcount: int):
            super().__init__()
            self.rowcount = rowcount

    class _Session(FakeSession):
        async def begin_nested(self):
            from unittest.mock import AsyncMock

            return AsyncMock()

        async def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            if sql.startswith("UPDATE") and "'superseded'" in sql:
                self.calls.append((sql, params or {}))
                return _RowcountResult(rowcount=len((params or {}).get("uuids") or []))
            return await super().execute(statement, params)

    return _Session()


def _v2_request(payload: dict) -> FakeRequest:
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    return FakeRequest(
        payload,
        headers={
            "Idempotency-Key": digest,
            "X-HealthSave-Payload-Hash": digest,
            "X-HealthSave-Sync-Run-ID": "elevation-run",
            "X-HealthSave-Batch-ID": "elevation-batch",
            "X-HealthSave-Metric": payload["metric"],
            "X-HealthSave-Batch-Index": str(payload["batch_index"]),
            "X-HealthSave-Total-Batches": str(payload["total_batches"]),
            "X-HealthSave-Schema-Version": str(payload["schema_version"]),
        },
    )


def _v2_payload(elevation) -> dict:
    payload = json.loads(V2_FIXTURE.read_text())
    payload = copy.deepcopy(payload)
    payload["samples"][0]["elevationGain"] = elevation
    return payload


@pytest.mark.asyncio
async def test_v2_route_validates_and_stores_elevation_gain() -> None:
    from server.api.v2_apple_batch import V2AppleBatchPayload, v2_apple_batch

    payload = _v2_payload(86.0)
    V2AppleBatchPayload.model_validate(payload)
    session = _v2_session()

    result = await v2_apple_batch(_v2_request(payload), None, session)

    assert result["status"] == "processed", result
    assert result["records_rejected"] == 0
    assert session.insert_params_for("workouts")["elevation_gain_m"] == 86.0


@pytest.mark.asyncio
async def test_v2_route_bad_value_is_not_an_error() -> None:
    from server.api.v2_apple_batch import v2_apple_batch

    session = _v2_session()

    result = await v2_apple_batch(_v2_request(_v2_payload("uphill")), None, session)

    assert result["status"] == "processed", result
    assert result["records_rejected"] == 0
    assert session.insert_params_for("workouts")["elevation_gain_m"] is None


# ─── canonical workout.session record ──────────────────────────────────


def test_canonical_workout_session_carries_elevation_gain_beside_distance() -> None:
    """The Apple normalizer keeps every sample field in the event summary."""

    result = normalize_apple_batch(
        {"metric": "workouts", "samples": [_workout(elevationGain=412.6)]},
        source_id=UUID("11111111-1111-1111-1111-111111111111"),
        provenance=Provenance(
            source_plugin_id="apple_health",
            sdk_version="0.1.0",
            captured_at=datetime(2026, 11, 18, tzinfo=UTC),
        ),
    )
    [observation] = result.observations
    assert observation.metric_id == "workout.session"
    assert observation.value.summary["distance"] == 11250
    assert observation.value.summary["elevationGain"] == 412.6
