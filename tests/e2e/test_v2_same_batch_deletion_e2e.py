"""E2E: a sample deleted in its own batch is gone from both stores.

HealthKit can deliver a sample and its deletion in one anchor window. The v2
route wrote the canonical rows, applied the deletions to both stores, and
only then projected the batch into the v1 tables, so the v1 projection
re-inserted the deleted sample as active: canonical said deleted, v1 (and
everything that reads it: status, Grafana, Home Assistant) said present.

A deleted sample must also never displace another row on its way through:
projecting it retired the active row already in its (time, device) slot as
"revised", and then the deletion retired the sample, leaving the slot empty
in v1 while canonical still had the first row active.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e",
    ),
]

OWNER = UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_a_sample_and_its_deletion_in_one_batch_leave_both_stores_agreeing() -> None:
    sample_uuid = str(uuid4())
    source = f"e2e same-batch deletion {uuid4()}"
    at = datetime(2025, 2, 1, tzinfo=UTC) + timedelta(microseconds=datetime.now().microsecond)
    body = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "source_bundle_id": "com.healthsave.ios",
        "device": {"name": "e2e", "model": "e2e-host"},
        "samples": [
            {
                "uuid": sample_uuid,
                "startDate": at.isoformat(),
                "endDate": at.isoformat(),
                "qty": 58,
                "unit": "count/min",
                "source": source,
                "tzOffsetMinutes": 0,
            }
        ],
        "deletions": [{"uuid": sample_uuid}],
    }
    headers = {"X-API-Key": API_KEY} if API_KEY else {}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        response = await client.post("/api/v2/apple/batch", json=body, headers=headers)
    assert response.status_code in (200, 201, 202), response.text[:400]

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        canonical = await conn.fetch(
            "SELECT status FROM canonical_observations "
            "WHERE owner_id = $1 AND source_record_uid = $2",
            OWNER,
            sample_uuid,
        )
        projected = await conn.fetch(
            "SELECT status FROM heart_rate WHERE owner_id = $1 AND source_uuid = $2",
            OWNER,
            UUID(sample_uuid),
        )
    finally:
        await conn.close()

    assert [row["status"] for row in canonical] == ["superseded"]
    assert "active" not in [row["status"] for row in projected]


def _v2_batch(source: str, at: datetime, sample_uuid: str, *, deletions=()) -> dict:
    return {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "source_bundle_id": "com.healthsave.ios",
        "device": {"name": "e2e", "model": "e2e-host"},
        "samples": [
            {
                "uuid": sample_uuid,
                "startDate": at.isoformat(),
                "endDate": at.isoformat(),
                "qty": 58,
                "unit": "count/min",
                "source": source,
                "tzOffsetMinutes": 0,
            }
        ],
        "deletions": [{"uuid": uuid} for uuid in deletions],
    }


@pytest.mark.asyncio
async def test_a_sample_deleted_in_its_own_batch_does_not_displace_the_slots_active_row() -> None:
    source = f"e2e same-batch slot {uuid4()}"
    at = datetime(2025, 3, 1, tzinfo=UTC) + timedelta(microseconds=datetime.now().microsecond)
    kept, deleted = str(uuid4()), str(uuid4())
    headers = {"X-API-Key": API_KEY} if API_KEY else {}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        first = await client.post(
            "/api/v2/apple/batch", json=_v2_batch(source, at, kept), headers=headers
        )
        assert first.status_code in (200, 201, 202), first.text[:400]
        # Same (time, device) slot, a different uuid, deleted in the same batch.
        second = await client.post(
            "/api/v2/apple/batch",
            json=_v2_batch(source, at, deleted, deletions=[deleted]),
            headers=headers,
        )
        assert second.status_code in (200, 201, 202), second.text[:400]

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        canonical = {
            row["source_record_uid"]: row["status"]
            for row in await conn.fetch(
                "SELECT source_record_uid, status FROM canonical_observations "
                "WHERE owner_id = $1 AND source_record_uid = ANY($2::text[])",
                OWNER,
                [kept, deleted],
            )
        }
        projected = {
            str(row["source_uuid"]): row["status"]
            for row in await conn.fetch(
                "SELECT source_uuid, status FROM heart_rate "
                "WHERE owner_id = $1 AND source_uuid = ANY($2::uuid[])",
                OWNER,
                [UUID(kept), UUID(deleted)],
            )
        }
    finally:
        await conn.close()

    assert canonical == {kept: "active", deleted: "superseded"}
    assert projected.get(kept) == "active"
    assert projected.get(deleted) != "active"
