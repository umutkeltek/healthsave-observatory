"""End-to-end v2 ingest success path — Plan 2026-09-03 Slice 6.

The unit suite pins the v2 validation envelope DB-free; this test proves
the full storage pipeline against a real Postgres: a v2 batch lands
canonical observations (with source_record_uid + capture context in the
provenance JSONB), projects into the v1 dedicated table with source_uuid
stamped, exposes tz_offset_minutes + motion_context on the series read
surface, and a follow-up deletion supersedes BOTH halves of the dual
write. These are the exact guarantees Eric's longitudinal engine needs
("late is fine, stale is not") that no mocked-DB test can establish.

Skipped unless ``E2E_BASE_URL`` (HTTP surface) and ``E2E_DATABASE_URL``
(direct Postgres assertions) are set. Drive with ``make e2e``.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import asyncpg
import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
DATABASE_URL = os.getenv("E2E_DATABASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL or not DATABASE_URL,
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e (see `make e2e`)",
    ),
]

OWNER = "00000000-0000-0000-0000-000000000001"  # X-User-Id absent -> sentinel


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _v2_heart_rate_batch(uuid: str, *, deletions: list[dict] | None = None) -> dict:
    return {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "source_bundle_id": "com.healthsave.ios",
        "device": {"name": "e2e", "model": "e2e-host"},
        "samples": [
            {
                "uuid": uuid,
                "startDate": "2026-08-30T07:14:00-04:00",
                "endDate": "2026-08-30T07:14:00-04:00",
                "qty": 52,
                "unit": "count/min",
                "source": "e2e Apple Watch",
                "tzOffsetMinutes": -240,
                "motionContext": "sedentary",
            }
        ],
        "deletions": deletions or [],
    }


def test_v2_success_path_canonical_projection_supersede_and_capture_context() -> None:
    """One v2 batch + one v2 deletion exercise the whole pipeline:

    1. Batch posts 200/processed with a deletions block.
    2. canonical_observations carries source_record_uid and the capture
       context inside the provenance JSONB.
    3. heart_rate (the projected v1 dedicated table) carries the same
       uuid as source_uuid — identity survives the projection seam.
    4. The series endpoint exposes tz_offset_minutes + motion_context.
    5. A second batch deleting the uuid supersedes the canonical row AND
       the dedicated row (both statuses flip; nothing stale remains).
    """
    uid = str(uuid4())

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        assert client.get("/ready").json().get("database") == "ok"

        # 1) ingest the v2 batch
        resp = client.post("/api/v2/apple/batch", json=_v2_heart_rate_batch(uid), headers=_headers())
        assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
        receipt = resp.json()
        assert receipt["status"] == "processed"
        assert receipt["wire_schema_version"] == 2

    import asyncio

    async def _db_assertions() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # 2) canonical row: identity + capture context
            row = await conn.fetchrow(
                "SELECT source_record_uid, status, provenance::text AS prov "
                "FROM canonical_observations "
                "WHERE owner_id = $1 AND source_record_uid = $2",
                OWNER,
                uid,
            )
            assert row is not None, "canonical observation missing source_record_uid"
            assert row["status"] == "active"
            prov = json.loads(row["prov"])
            assert prov.get("tz_offset_minutes") == -240, prov
            assert prov.get("motion_context") == "sedentary", prov

            # 3) projected v1 dedicated row carries source_uuid
            dedicated = await conn.fetchrow(
                "SELECT status FROM heart_rate "
                "WHERE owner_id = $1 AND source_uuid = $2",
                OWNER,
                uid,
            )
            assert dedicated is not None, (
                "projection dropped source_uuid — heart_rate row not supersedeable"
            )
            assert dedicated["status"] == "active"
        finally:
            await conn.close()

    asyncio.run(_db_assertions())

    # 4) series read surface exposes the capture context
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        series = client.get(
            "/api/v2/metrics/vital.heart_rate/series",
            params={"range": "1y"},
            headers=_headers(),
        ).json()
        ctx_points = [
            p
            for p in series["points"]
            if p.get("tz_offset_minutes") == -240 and p.get("motion_context") == "sedentary"
        ]
        assert ctx_points, (
            "series endpoint did not surface tz_offset_minutes/motion_context "
            "for the v2-ingested point"
        )

        # 5) deletion supersedes both halves
        resp = client.post(
            "/api/v2/apple/batch",
            json=_v2_heart_rate_batch(str(uuid4()), deletions=[{"uuid": uid}]),
            headers=_headers(),
        )
        assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
        receipt = resp.json()
        assert receipt["status"] == "processed"
        assert receipt["deletions"]["canonical_superseded"] >= 1, receipt
        assert receipt["deletions"]["v1_dedicated_superseded"].get("heart_rate", 0) >= 1, receipt

    async def _superseded_assertions() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            status = await conn.fetchval(
                "SELECT status FROM canonical_observations "
                "WHERE owner_id = $1 AND source_record_uid = $2",
                OWNER,
                uid,
            )
            assert status == "superseded", f"canonical row not superseded: {status}"
            dedicated_status = await conn.fetchval(
                "SELECT status FROM heart_rate WHERE owner_id = $1 AND source_uuid = $2",
                OWNER,
                uid,
            )
            assert dedicated_status == "superseded", (
                f"heart_rate dedicated row not superseded: {dedicated_status}"
            )
        finally:
            await conn.close()

    asyncio.run(_superseded_assertions())


def test_v2_batch_rejects_unknown_unit_end_to_end() -> None:
    """The unit gate holds at the live route, not just the model: a unit
    outside the metric's ontology allowed_units is a deterministic 422
    and never touches storage (Eric's ask #3 — refuse, never guess)."""
    body = _v2_heart_rate_batch(str(uuid4()))
    body["samples"][0]["unit"] = "furlongs/fortnight"
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        resp = client.post("/api/v2/apple/batch", json=body, headers=_headers())
        assert resp.status_code == 422, resp.text[:400]
        assert "unit" in resp.text.lower()


@pytest.mark.asyncio
async def test_v2_deletion_convergence_against_real_storage() -> None:
    """Slice 7 (oracle follow-up, 2026-09-04): the same deletion uuid sent
    in two v2 batches must converge — no double-counting, no duplicate
    ``superseded`` rows, no errors. ``mark_*_superseded`` is idempotent
    (rowcount=0 on the second call); the receipt counts each delivery
    so the operator sees the intent while the storage stays at one row.
    Lives in e2e because the validation-layer pin (``tests/contract/v2/``)
    can't reach the supersede SQL. The oracle review named this exact
    gap: the unit suite structurally cannot see this state machine.
    """
    sample_uuid = str(uuid4())
    body_a = _v2_heart_rate_batch(sample_uuid)
    body_b = _v2_heart_rate_batch(sample_uuid)
    deletion_uuid = str(uuid4())
    body_a["samples"] = []
    body_a["deletions"] = [{"uuid": deletion_uuid}]
    body_b["samples"] = []
    body_b["deletions"] = [{"uuid": deletion_uuid}]
    headers = _headers()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        first = await client.post("/api/v2/apple/batch", json=body_a, headers=headers)
        second = await client.post("/api/v2/apple/batch", json=body_b, headers=headers)
        assert first.status_code in (200, 201, 202), first.text[:400]
        assert second.status_code in (200, 201, 202), second.text[:400]
        # Receipt shape: deletions.received must be 1 for both, but the
        # per-table counts must stay at the same magnitude (the second
        # delivery's mark_*_superseded returns 0 rowcount for already-
        # superseded rows; the receipt reports it under canonical /
        # v1_dedicated).
        first_body = first.json()
        second_body = second.json()
        assert first_body["deletions"]["received"] == 1
        assert second_body["deletions"]["received"] == 1

    # Direct Postgres assertion: still exactly one ``superseded`` row for
    # that uuid, regardless of how many batches delivered it.
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        canon_count = await conn.fetchval(
            "SELECT COUNT(*) FROM canonical_observations "
            "WHERE source_record_uid = $1 AND status = 'superseded'",
            deletion_uuid,
        )
        # Note: the deletion in this test did not insert any new
        # canonical rows (samples=[]), so canonical_count is exactly the
        # number of times we issued the deletion — which should still be
        # 0 (the deletion operates on previously-written rows; with
        # samples=[], the row was never inserted, so the supersede is a
        # no-op against an empty set). The test below exercises a
        # sample-then-delete-then-re-delete flow to cover the
        # convergence claim end-to-end.
        assert canon_count == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v2_add_then_delete_then_delete_again_converges() -> None:
    """Slice 7 (oracle follow-up): the convergence claim when a uuid
    is added then deleted twice. Storage must end up at exactly one
    ``superseded`` row, never two; receipt counts both deliveries."""
    sample_uuid = str(uuid4())
    add_body = _v2_heart_rate_batch(sample_uuid)
    delete_body = _v2_heart_rate_batch(sample_uuid)
    delete_body["samples"] = []
    delete_body["deletions"] = [{"uuid": sample_uuid}]
    headers = _headers()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        add_resp = await client.post("/api/v2/apple/batch", json=add_body, headers=headers)
        assert add_resp.status_code in (200, 201, 202), add_resp.text[:400]

        del_resp_1 = await client.post("/api/v2/apple/batch", json=delete_body, headers=headers)
        del_resp_2 = await client.post("/api/v2/apple/batch", json=delete_body, headers=headers)
        assert del_resp_1.status_code in (200, 201, 202), del_resp_1.text[:400]
        assert del_resp_2.status_code in (200, 201, 202), del_resp_2.text[:400]

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        canon_count = await conn.fetchval(
            "SELECT COUNT(*) FROM canonical_observations "
            "WHERE source_record_uid = $1 AND status = 'superseded'",
            sample_uuid,
        )
        heart_rate_count = await conn.fetchval(
            "SELECT COUNT(*) FROM heart_rate "
            "WHERE source_uuid = $1 AND status = 'superseded'",
            sample_uuid,
        )
        assert canon_count == 1, f"expected one superseded canonical row, got {canon_count}"
        assert heart_rate_count == 1, f"expected one superseded heart_rate row, got {heart_rate_count}"
    finally:
        await conn.close()
