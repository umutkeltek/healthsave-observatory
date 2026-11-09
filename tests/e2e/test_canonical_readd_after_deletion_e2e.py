"""E2E: a HealthKit sample re-added after its deletion is active again in canonical.

HKSample.uuid survives delete-and-reinsert (an iCloud Health re-sync or a
restore brings back the same sample under the same uuid). The canonical
upsert only updated rows still 'active', so a re-add in a later request than
the deletion matched the superseded row, updated nothing and was silently
dropped. A deletion in the same request as the write still wins: the v2 route
writes the batch's samples first and applies its deletions after.

Runs the real canonical repository and deletion helper on PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]

APPLE_SOURCE = UUID("a9b1e7e0-0000-4000-8000-000000000001")


def _heart_rate(owner: UUID, uid: str, at: datetime, *, bpm: float, raw_ref: int):
    from contracts._base import Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import QuantityValue

    from contracts import DEFAULT_WORKSPACE_ID

    return Observation(
        owner_id=owner,
        workspace_id=DEFAULT_WORKSPACE_ID,
        metric_id="vital.heart_rate",
        value=QuantityValue(
            type="quantity",
            value=bpm,
            unit="count/min",
            canonical_value=bpm,
            canonical_unit="count/min",
        ),
        interval_start=at,
        interval_end=at,
        source_id=APPLE_SOURCE,
        source_record_uid=uid,
        provenance=Provenance(
            source_plugin_id="apple-health-healthsave",
            sdk_version="1",
            captured_at=datetime.now(UTC),
            raw_payload_ref=str(raw_ref),
        ),
        normalizer_id="apple_health",
        normalizer_version="1",
        dedup_key=build_dedup_key(
            owner_id=owner,
            workspace_id=DEFAULT_WORKSPACE_ID,
            source_id=APPLE_SOURCE,
            metric_id="vital.heart_rate",
            interval_start=at,
            interval_end=at,
            source_record_uid=uid,
        ),
    )


@pytest.fixture
async def db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = uuid4()
    try:
        yield factory, owner
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM canonical_observations WHERE owner_id = :owner"),
                {"owner": owner},
            )
            await session.commit()
        await engine.dispose()


async def _rows(session, owner: UUID) -> list[tuple[str, float]]:
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT status, numeric_value FROM canonical_observations WHERE owner_id = :owner"),
        {"owner": owner},
    )
    return [(row.status, row.numeric_value) for row in result]


@pytest.mark.asyncio
async def test_a_sample_re_added_after_its_deletion_is_active_again(db) -> None:
    from storage.timescale.measurements import mark_canonical_observations_superseded
    from storage.timescale.observations import default_repository

    factory, owner = db
    uid = str(uuid4()).upper()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    async with factory() as session:  # request 1: the sample
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=61, raw_ref=1)]
        )
        await session.commit()
    async with factory() as session:  # request 2: its deletion
        await mark_canonical_observations_superseded(session, owner_id=owner, uuids=[uid])
        await session.commit()
        assert await _rows(session, owner) == [("superseded", 61)]
    async with factory() as session:  # request 3: the same sample, restored
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=62, raw_ref=3)]
        )
        await session.commit()
        assert await _rows(session, owner) == [("active", 62)]


@pytest.mark.asyncio
async def test_a_deletion_in_the_same_request_still_wins(db) -> None:
    """The v2 route writes a batch's samples, then applies its deletions."""
    from storage.timescale.measurements import mark_canonical_observations_superseded
    from storage.timescale.observations import default_repository

    factory, owner = db
    uid = str(uuid4()).upper()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    async with factory() as session:
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=61, raw_ref=1)]
        )
        await session.commit()
    async with factory() as session:
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=62, raw_ref=2)]
        )
        await mark_canonical_observations_superseded(session, owner_id=owner, uuids=[uid])
        await session.commit()
        assert await _rows(session, owner) == [("superseded", 62)]


@pytest.mark.asyncio
async def test_an_older_copy_does_not_reactivate_a_deleted_sample(db) -> None:
    """The recency ladder still applies: only a later request reactivates."""
    from storage.timescale.measurements import mark_canonical_observations_superseded
    from storage.timescale.observations import default_repository

    factory, owner = db
    uid = str(uuid4()).upper()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    async with factory() as session:
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=61, raw_ref=5)]
        )
        await mark_canonical_observations_superseded(session, owner_id=owner, uuids=[uid])
        await session.commit()
    async with factory() as session:
        await default_repository.insert_many(
            session, [_heart_rate(owner, uid, at, bpm=60, raw_ref=4)]
        )
        await session.commit()
        assert await _rows(session, owner) == [("superseded", 61)]
