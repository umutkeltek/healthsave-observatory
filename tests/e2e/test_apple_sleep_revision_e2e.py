"""E2E: a revised sleep session is stored, not rejected.

HealthKit reshuffles a night by deleting its stages and inserting new ones, so
the same night can arrive again with new stage uuids at the same start time.

Through the API today the session row never carries a uuid
(``sleep_stage_segments`` does not keep it), so a revision takes the legacy
``(device_id, start_time, owner_id)`` upsert and updates the night in place.
The uuid arm of ``_upsert_sleep_session`` is not reached, but if it were, a
new first-stage uuid missed the ``(owner_id, source_uuid)`` arbiter and hit
the active-slot index ``(device_id, start_time, owner_id) WHERE status =
'active'``: a deterministic 422 that retires the whole batch, canonical rows
included. The storage-level tests below pin that arm on real PostgreSQL.
"""

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
START = datetime(2026, 8, 1, 22, 30, tzinfo=UTC)


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _stage(uuid: str, start: str, end: str, value: str, source: str) -> dict:
    return {"uuid": uuid, "startDate": start, "endDate": end, "value": value, "source": source}


def _night(source: str, first_uuid: str, second_uuid: str, *, deep_end: str) -> dict:
    return {
        "metric": "sleep_analysis",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            _stage(
                first_uuid,
                "2026-08-01T22:30:00.000Z",
                "2026-08-02T01:00:00.000Z",
                "Core",
                source,
            ),
            _stage(
                second_uuid,
                "2026-08-02T01:00:00.000Z",
                deep_end,
                "Deep",
                source,
            ),
        ],
    }


async def _sessions(source: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch(
            """
            SELECT s.source_uuid, s.status, s.end_time
              FROM sleep_sessions AS s
              JOIN devices AS d ON d.id = s.device_id
             WHERE d.device_type = $1 AND s.start_time = $2 AND s.owner_id = $3
             ORDER BY s.id
            """,
            source,
            START,
            OWNER,
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/api/apple/batch", "/api/v2/apple/batch"])
async def test_a_revised_night_through_the_api_is_stored_not_rejected(route: str) -> None:
    source = f"e2e sleep revision {uuid4()}"
    first = _night(source, str(uuid4()), str(uuid4()), deep_end="2026-08-02T02:15:00.000Z")
    revision = _night(source, str(uuid4()), str(uuid4()), deep_end="2026-08-02T02:45:00.000Z")
    if route.startswith("/api/v2/"):
        for body in (first, revision):
            body["schema_version"] = 2
            body["deletions"] = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        stored = await client.post(route, json=first, headers=_headers())
        assert stored.status_code in (200, 201, 202), stored.text[:400]
        response = await client.post(route, json=revision, headers=_headers())

    assert response.status_code in (200, 201, 202), (
        f"sleep revision was rejected: {response.status_code} {response.text[:400]}"
    )
    rows = await _sessions(source)
    active = [r for r in rows if r["status"] == "active"]
    assert len(active) == 1
    assert active[0]["end_time"] == datetime(2026, 8, 2, 2, 45, tzinfo=UTC)


async def _device(source: str) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id", source
        )
    finally:
        await conn.close()


def _session_row(device_id: int, source_uuid: str, end: datetime) -> dict:
    return {
        "device_id": device_id,
        "start": START,
        "end": end,
        "total": 1,
        "deep": 1,
        "rem": 0,
        "light": 0,
        "awake": 0,
        "rr": None,
        "owner_id": str(OWNER),
        "source_id": None,
        "source_uuid": source_uuid,
    }


async def _write_nights(*rows: dict) -> None:
    """Write each row through the storage writer in its own committed transaction."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from storage.timescale.measurements import _upsert_sleep_session

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        for row in rows:
            async with AsyncSession(engine) as session:
                await _upsert_sleep_session(session, dict(row))
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_new_first_stage_uuid_supersedes_the_night_it_revises() -> None:
    source = f"e2e sleep uuid revision {uuid4()}"
    device_id = await _device(source)
    original, revised = str(uuid4()), str(uuid4())

    await _write_nights(
        _session_row(device_id, original, datetime(2026, 8, 2, 2, 15, tzinfo=UTC)),
        _session_row(device_id, revised, datetime(2026, 8, 2, 2, 45, tzinfo=UTC)),
    )

    rows = await _sessions(source)
    assert [(str(r["source_uuid"]), r["status"]) for r in rows] == [
        (original, "superseded"),
        (revised, "active"),
    ]
    assert rows[1]["end_time"] == datetime(2026, 8, 2, 2, 45, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_replayed_old_revision_does_not_retire_the_newer_night() -> None:
    source = f"e2e sleep uuid replay {uuid4()}"
    device_id = await _device(source)
    original, revised = str(uuid4()), str(uuid4())
    first = _session_row(device_id, original, datetime(2026, 8, 2, 2, 15, tzinfo=UTC))
    second = _session_row(device_id, revised, datetime(2026, 8, 2, 2, 45, tzinfo=UTC))

    await _write_nights(first, second, first)

    rows = await _sessions(source)
    assert [(str(r["source_uuid"]), r["status"]) for r in rows] == [
        (original, "superseded"),
        (revised, "active"),
    ]


@pytest.mark.asyncio
async def test_a_uuid_bearing_night_adopts_a_legacy_session_row() -> None:
    source = f"e2e sleep uuid legacy {uuid4()}"
    device_id = await _device(source)
    first_uuid = str(uuid4())
    legacy = _session_row(device_id, first_uuid, datetime(2026, 8, 2, 2, 15, tzinfo=UTC))
    legacy["source_uuid"] = None

    await _write_nights(
        legacy,
        _session_row(device_id, first_uuid, datetime(2026, 8, 2, 2, 30, tzinfo=UTC)),
    )

    rows = await _sessions(source)
    assert [(str(r["source_uuid"]), r["status"]) for r in rows] == [(first_uuid, "active")]
    assert rows[0]["end_time"] == datetime(2026, 8, 2, 2, 30, tzinfo=UTC)
