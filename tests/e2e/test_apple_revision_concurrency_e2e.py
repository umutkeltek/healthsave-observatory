"""Real PostgreSQL regression for overlapping UUID revisions of one active slot."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.measurements import _ingest_dedicated

DATABASE_URL = os.getenv("E2E_DATABASE_URL")
OWNER = UUID("00000000-0000-0000-0000-000000000001")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL for real PostgreSQL proof"),
]


@pytest.mark.asyncio
async def test_active_uuid_can_move_to_a_revised_device_slot_without_rejection() -> None:
    """Source attribution can change while sample identity stays stable.

    The UUID upsert already updates device_id. Its supersede preflight must
    distinguish an active identity moving slots from a superseded old replay.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
    sample_time = datetime(2026, 9, 25, 8, 43, tzinfo=UTC)
    active_uuid, replaced_uuid = str(uuid4()), str(uuid4())
    try:
        original_device = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            f"e2e original attribution {uuid4()}",
        )
        corrected_device = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            f"e2e corrected attribution {uuid4()}",
        )
        async with AsyncSession(engine) as session:
            for device, uid in (
                (original_device, active_uuid),
                (corrected_device, replaced_uuid),
                (corrected_device, active_uuid),
                (corrected_device, replaced_uuid),
            ):
                await _ingest_dedicated(
                    session,
                    device,
                    "heart_rate",
                    [
                        {
                            "date": sample_time.isoformat(),
                            "qty": 72,
                            "uuid": uid,
                        }
                    ],
                )
                await session.commit()
        active_rows = await conn.fetch(
            "SELECT source_uuid, device_id FROM heart_rate "
            "WHERE device_id = ANY($1) AND status = 'active'",
            [original_device, corrected_device],
        )
        assert [(str(r["source_uuid"]), r["device_id"]) for r in active_rows] == [
            (active_uuid, corrected_device)
        ]
    finally:
        await engine.dispose()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_row", [False, True], ids=["empty-slot", "revised-slot"])
async def test_concurrent_uuid_revisions_do_not_reject_the_batch(existing_row: bool) -> None:
    """Hold one revision uncommitted until another writer waits on its slot.

    With an existing row, the second UPDATE's snapshot sees the original but
    cannot see the first writer's replacement. Without one, both UPDATEs find
    nothing. In either case the second INSERT used to collide with the active
    slot index after the first transaction committed.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
    device_name = f"e2e concurrent revision {uuid4()}"
    sample_time = datetime(2026, 9, 25, 8, 43, tzinfo=UTC)
    original_uuid, first_uuid, second_uuid = (str(uuid4()) for _ in range(3))

    def sample(uid: str, value: int) -> dict:
        return {"date": sample_time.isoformat(), "qty": value, "uuid": uid, "source": device_name}

    second_task = None
    try:
        device_id = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id", device_name
        )
        if existing_row:
            async with AsyncSession(engine) as seed:
                await _ingest_dedicated(seed, device_id, "heart_rate", [sample(original_uuid, 70)])
                await seed.commit()

        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await _ingest_dedicated(first, device_id, "heart_rate", [sample(first_uuid, 72)])
            second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

            async def write_second() -> None:
                await _ingest_dedicated(second, device_id, "heart_rate", [sample(second_uuid, 75)])
                await second.commit()

            second_task = asyncio.create_task(write_second())
            try:
                async with asyncio.timeout(10):
                    while not second_task.done():
                        wait_type = await conn.fetchval(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = $1",
                            second_pid,
                        )
                        if wait_type == "Lock":
                            break
                        await asyncio.sleep(0.01)
                    assert not second_task.done(), "second writer must overlap the open transaction"
            finally:
                # Always release our synthetic transaction, including a failed assertion.
                await first.commit()
                await second_task

        rows = await conn.fetch(
            "SELECT source_uuid, status FROM heart_rate "
            "WHERE time = $1 AND device_id = $2 AND owner_id = $3",
            sample_time,
            device_id,
            OWNER,
        )
        assert [str(r["source_uuid"]) for r in rows if r["status"] == "active"] == [second_uuid]

        # A delayed outbox replay must not bring the older revision back to life.
        async with AsyncSession(engine) as replay:
            await _ingest_dedicated(replay, device_id, "heart_rate", [sample(first_uuid, 72)])
            await replay.commit()
        active_uuid = await conn.fetchval(
            "SELECT source_uuid FROM heart_rate "
            "WHERE time = $1 AND device_id = $2 AND owner_id = $3 AND status = 'active'",
            sample_time,
            device_id,
            OWNER,
        )
        assert str(active_uuid) == second_uuid
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        await engine.dispose()
        await conn.close()


@pytest.mark.asyncio
async def test_concurrently_superseded_reattribution_cannot_retire_destination() -> None:
    """An incoming identity may become old while its upsert waits on a writer."""
    conn = await asyncpg.connect(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
    sample_time = datetime(2026, 9, 25, 8, 43, tzinfo=UTC)
    original_uuid, destination_uuid, revision_uuid = (str(uuid4()) for _ in range(3))
    second_task = None

    def sample(uid):
        return {"date": sample_time.isoformat(), "qty": 72, "uuid": uid}

    try:
        original_device = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            f"e2e source old race {uuid4()}",
        )
        destination_device = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id",
            f"e2e source destination race {uuid4()}",
        )
        async with AsyncSession(engine) as seed:
            await _ingest_dedicated(seed, original_device, "heart_rate", [sample(original_uuid)])
            await _ingest_dedicated(
                seed, destination_device, "heart_rate", [sample(destination_uuid)]
            )
            await seed.commit()
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await _ingest_dedicated(first, original_device, "heart_rate", [sample(revision_uuid)])
            second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()

            async def write_second():
                await _ingest_dedicated(
                    second, destination_device, "heart_rate", [sample(original_uuid)]
                )
                await second.commit()

            second_task = asyncio.create_task(write_second())
            try:
                async with asyncio.timeout(10):
                    while not second_task.done():
                        if (
                            await conn.fetchval(
                                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = $1",
                                second_pid,
                            )
                            == "Lock"
                        ):
                            break
                        await asyncio.sleep(0.01)
                    assert not second_task.done(), "must overlap the superseding transaction"
            finally:
                await first.commit()
                await second_task
        active_rows = await conn.fetch(
            "SELECT source_uuid, device_id FROM heart_rate "
            "WHERE device_id = ANY($1) AND status = 'active' ORDER BY device_id",
            [original_device, destination_device],
        )
        assert [(str(r["source_uuid"]), r["device_id"]) for r in active_rows] == [
            (revision_uuid, original_device),
            (destination_uuid, destination_device),
        ]
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        await engine.dispose()
        await conn.close()


@pytest.mark.asyncio
async def test_v2_revision_race_commits_canonical_audit_and_projection_together() -> None:
    """Run the live v2 handler against PostgreSQL while another revision is open."""
    from server.api.v2_apple_batch import v2_apple_batch

    from tests.test_api_contract import FakeRequest

    conn = await asyncpg.connect(DATABASE_URL)
    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
    device_name = f"e2e v2 concurrent revision {uuid4()}"
    sample_time = datetime(2026, 9, 25, 8, 43, tzinfo=UTC)
    first_uuid, second_uuid = str(uuid4()), str(uuid4())
    payload = {
        "schema_version": 2,
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": second_uuid,
                "startDate": sample_time.isoformat(),
                "endDate": sample_time.isoformat(),
                "qty": 75,
                "unit": "count/min",
                "source": device_name,
            }
        ],
    }
    request_task = None
    try:
        device_id = await conn.fetchval(
            "INSERT INTO devices (device_type) VALUES ($1) RETURNING id", device_name
        )
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await _ingest_dedicated(
                first,
                device_id,
                "heart_rate",
                [
                    {
                        "date": sample_time.isoformat(),
                        "qty": 72,
                        "source": device_name,
                        "uuid": first_uuid,
                    }
                ],
            )
            second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            request_task = asyncio.create_task(v2_apple_batch(FakeRequest(payload), None, second))
            try:
                async with asyncio.timeout(10):
                    while not request_task.done():
                        if (
                            await conn.fetchval(
                                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = $1",
                                second_pid,
                            )
                            == "Lock"
                        ):
                            break
                        await asyncio.sleep(0.01)
                    assert not request_task.done(), "v2 must overlap the open revision transaction"
            finally:
                await first.commit()
                response = await request_task
        assert response["status"] == "processed"
        assert response["wire_schema_version"] == 2
        assert response["records_accepted"] == 1
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM canonical_observations WHERE source_record_uid = $1",
                second_uuid,
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM raw_ingestion_log WHERE device_id = $1 AND processed",
                device_id,
            )
            == 1
        )
        assert (
            str(
                await conn.fetchval(
                    "SELECT source_uuid FROM heart_rate WHERE device_id = $1 AND status = 'active'",
                    device_id,
                )
            )
            == second_uuid
        )

        # A full v2 replay is a success, not another insert or resurrection.
        async with AsyncSession(engine) as replay:
            replay_response = await v2_apple_batch(FakeRequest(payload), None, replay)
        assert replay_response["status"] == "processed"
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM heart_rate WHERE device_id = $1 AND status = 'active'",
                device_id,
            )
            == 1
        )
        payload["samples"][0]["uuid"] = first_uuid
        payload["samples"][0]["qty"] = 72
        async with AsyncSession(engine) as old_replay:
            old_response = await v2_apple_batch(FakeRequest(payload), None, old_replay)
        assert old_response["status"] == "processed"
        assert (
            str(
                await conn.fetchval(
                    "SELECT source_uuid FROM heart_rate WHERE device_id = $1 AND status = 'active'",
                    device_id,
                )
            )
            == second_uuid
        )
    finally:
        if request_task is not None and not request_task.done():
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        await engine.dispose()
        await conn.close()
