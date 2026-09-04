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
