"""E2E regression: UUID-bearing Apple samples must reconcile legacy rows."""

from __future__ import annotations

import os
from datetime import UTC, datetime
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


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


@pytest.mark.asyncio
async def test_uuid_sample_reconciles_existing_legacy_heart_rate_row() -> None:
    """A UUID-bearing retry must not collide with the legacy active-row index."""
    device_type = f"e2e legacy uuid {uuid4()}"
    sample_uuid = str(uuid4())
    sample_time = datetime(2026, 9, 1, 12, 34, 56, tzinfo=UTC)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        device_id = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            device_type,
        )
        await conn.execute(
            """
            INSERT INTO heart_rate (time, device_id, bpm, owner_id)
            VALUES ($1, $2, $3, $4)
            """,
            sample_time,
            device_id,
            72,
            OWNER,
        )
    finally:
        await conn.close()

    payload = {
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "date": sample_time.isoformat(),
                "qty": 72,
                "source": device_type,
                "uuid": sample_uuid,
            }
        ],
    }

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        response = await client.post("/api/apple/batch", json=payload, headers=_headers())

    assert response.status_code in (200, 201, 202), (
        f"UUID retry collided with existing legacy row: "
        f"{response.status_code} {response.text[:400]}"
    )

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT source_uuid, status
            FROM heart_rate
            WHERE time = $1
              AND device_id = $2
              AND owner_id = $3
              AND status = 'active'
            """,
            sample_time,
            device_id,
            OWNER,
        )
    finally:
        await conn.close()

    assert len(rows) == 1
    assert str(rows[0]["source_uuid"]) == sample_uuid


@pytest.mark.asyncio
async def test_uuid_sample_reconciles_existing_legacy_hrv_row() -> None:
    """A UUID-bearing HRV retry must reconcile the matching legacy row."""
    device_type = f"e2e legacy hrv uuid {uuid4()}"
    sample_uuid = str(uuid4())
    sample_time = datetime(2026, 9, 1, 12, 35, 56, tzinfo=UTC)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        device_id = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            device_type,
        )
        await conn.execute(
            """
            INSERT INTO hrv (time, device_id, value_ms, owner_id)
            VALUES ($1, $2, $3, $4)
            """,
            sample_time,
            device_id,
            48.5,
            OWNER,
        )
    finally:
        await conn.close()

    payload = {
        "metric": "heart_rate_variability",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "date": sample_time.isoformat(),
                "qty": 48.5,
                "source": device_type,
                "uuid": sample_uuid,
            }
        ],
    }

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        response = await client.post("/api/apple/batch", json=payload, headers=_headers())

    assert response.status_code in (200, 201, 202), (
        f"UUID HRV retry collided with existing legacy row: "
        f"{response.status_code} {response.text[:400]}"
    )

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT source_uuid, status
            FROM hrv
            WHERE time = $1
              AND device_id = $2
              AND owner_id = $3
              AND status = 'active'
            """,
            sample_time,
            device_id,
            OWNER,
        )
    finally:
        await conn.close()

    assert len(rows) == 1
    assert str(rows[0]["source_uuid"]) == sample_uuid


async def _post_heart_rate(samples: list[dict]) -> httpx.Response:
    payload = {
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": samples,
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        return await client.post("/api/apple/batch", json=payload, headers=_headers())


async def _heart_rate_rows(device_type: str, sample_time: datetime) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch(
            """
            SELECT h.source_uuid, h.status, h.bpm
            FROM heart_rate h
            JOIN devices d ON d.id = h.device_id
            WHERE h.time = $1
              AND d.device_type = $2
              AND h.owner_id = $3
            """,
            sample_time,
            device_type,
            OWNER,
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_revised_sample_under_a_new_uuid_supersedes_the_old_row() -> None:
    """Apple Health revises a sample by deleting it and re-inserting it under a new
    HKSample uuid at the same timestamp. The batch carrying the revision must land."""
    device_type = f"e2e revised uuid {uuid4()}"
    original_uuid = str(uuid4())
    revised_uuid = str(uuid4())
    sample_time = datetime(2026, 9, 1, 12, 36, 56, tzinfo=UTC)

    first = await _post_heart_rate(
        [{"date": sample_time.isoformat(), "qty": 72, "source": device_type, "uuid": original_uuid}]
    )
    assert first.status_code in (200, 201, 202), first.text[:400]

    revised = await _post_heart_rate(
        [{"date": sample_time.isoformat(), "qty": 75, "source": device_type, "uuid": revised_uuid}]
    )
    assert revised.status_code in (200, 201, 202), (
        f"revised uuid collided with the active row: {revised.status_code} {revised.text[:400]}"
    )

    rows = await _heart_rate_rows(device_type, sample_time)
    active = [r for r in rows if r["status"] == "active"]
    assert len(active) == 1
    assert str(active[0]["source_uuid"]) == revised_uuid
    assert active[0]["bpm"] == 75
    superseded = [r for r in rows if r["status"] == "superseded"]
    assert [str(r["source_uuid"]) for r in superseded] == [original_uuid]


@pytest.mark.asyncio
async def test_replaying_the_older_revision_leaves_the_newer_one_active() -> None:
    """An outbox replay can deliver the old revision after the new one."""
    device_type = f"e2e revised replay {uuid4()}"
    original_uuid = str(uuid4())
    revised_uuid = str(uuid4())
    sample_time = datetime(2026, 9, 1, 12, 37, 56, tzinfo=UTC)
    original = {
        "date": sample_time.isoformat(),
        "qty": 72,
        "source": device_type,
        "uuid": original_uuid,
    }
    revision = {
        "date": sample_time.isoformat(),
        "qty": 75,
        "source": device_type,
        "uuid": revised_uuid,
    }

    for sample in (original, revision, original):
        response = await _post_heart_rate([sample])
        assert response.status_code in (200, 201, 202), response.text[:400]

    rows = await _heart_rate_rows(device_type, sample_time)
    active = [r for r in rows if r["status"] == "active"]
    assert [str(r["source_uuid"]) for r in active] == [revised_uuid]


@pytest.mark.asyncio
async def test_two_uuids_at_one_timestamp_in_one_batch_land_as_one_active_row() -> None:
    """The dedicated tables hold one active row per (time, device, owner); the last one wins,
    as it always has for samples without a uuid."""
    device_type = f"e2e same batch {uuid4()}"
    first_uuid = str(uuid4())
    last_uuid = str(uuid4())
    sample_time = datetime(2026, 9, 1, 12, 38, 56, tzinfo=UTC)

    response = await _post_heart_rate(
        [
            {"date": sample_time.isoformat(), "qty": 72, "source": device_type, "uuid": first_uuid},
            {"date": sample_time.isoformat(), "qty": 75, "source": device_type, "uuid": last_uuid},
        ]
    )
    assert response.status_code in (200, 201, 202), response.text[:400]

    rows = await _heart_rate_rows(device_type, sample_time)
    active = [r for r in rows if r["status"] == "active"]
    assert [str(r["source_uuid"]) for r in active] == [last_uuid]
