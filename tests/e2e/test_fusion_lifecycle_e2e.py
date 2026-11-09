"""E2E: a fused workout stays fused, a rejected pair is decided once, and a link
that stops qualifying unfuses what it fused.

Session fusion marks a direct vendor workout (Whoop) and the same workout
relayed through Apple Health as one logical event: both rows get a semantic
key and only the primary counts. Three lifecycle edges, on real PostgreSQL:

* The phone re-sends its copy of the workout (same HealthKit uuid). The
  canonical upsert used to write the incoming row's empty semantic key and
  ``is_primary = true`` over the fusion, so both copies counted again, and the
  candidate query (both keys NULL) never fused them back.
* A pair the matcher rejects was offered again on every poll, appending one
  more ``rejected`` row each time and holding a slot in the candidate limit.
* A device link moved off ``confirmed`` left the pairs it had fused fused;
  ``revoked`` had no writer.
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

APPLE_STREAM = UUID("5e1f0000-0000-4000-8000-0000000000a1")
APPLE_SOURCE = UUID("a9b1e7e0-0000-4000-8000-000000000001")


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
            for table in ("fusion_decisions", "device_identity_links", "canonical_observations"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE owner_id = :owner"), {"owner": owner}
                )
            await session.commit()
        await engine.dispose()


def _whoop_workout(owner: UUID, start: datetime, end: datetime):
    from plugins.sources.whoop.normalize import canonical_session_observations

    [observation] = canonical_session_observations(
        [
            {
                "id": "whoop-workout-1",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "sport_id": 0,
                "score_state": "SCORED",
                "score": {"kilojoule": 1200.0},
            }
        ],
        owner_id=owner,
        provider_subject_id="whoop-user-1",
    )
    return observation


def _apple_workout(owner: UUID, start: datetime, end: datetime, *, activity: str, raw_ref: int):
    from contracts._base import Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import EventValue

    from contracts import DEFAULT_WORKSPACE_ID

    uid = "apple-workout-uuid-1"
    return Observation(
        owner_id=owner,
        workspace_id=DEFAULT_WORKSPACE_ID,
        metric_id="workout.session",
        value=EventValue(
            type="event",
            label=activity,
            status="completed",
            summary={"activity_type": activity, "vendor_family": "whoop"},
        ),
        interval_start=start,
        interval_end=end,
        source_id=APPLE_SOURCE,
        stream_id=APPLE_STREAM,
        aggregation_scope="interval_component",
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
            metric_id="workout.session",
            interval_start=start,
            interval_end=end,
            source_record_uid=uid,
        ),
    )


async def _link(session, owner: UUID, direct_stream: UUID, *, status: str, confidence: str):
    from normalization.fusion import DeviceLinkConfidence
    from storage.timescale.fusion import default_repository

    await default_repository.upsert_device_identity_link(
        session,
        owner_id=owner,
        direct_stream_id=direct_stream,
        relayed_stream_id=APPLE_STREAM,
        status=status,
        confidence=DeviceLinkConfidence(confidence),
        evidence={"vendor_family": "whoop"},
    )


async def _reconcile(session, owner: UUID) -> int:
    """The worker's post-poll loop (worker.sources.reconcile_source_poll_sessions)."""
    from storage.timescale.fusion import default_repository

    from contracts import DEFAULT_WORKSPACE_ID

    pairs = await default_repository.find_session_candidate_pairs(
        session, owner_id=owner, workspace_id=DEFAULT_WORKSPACE_ID
    )
    for pair in pairs:
        await default_repository.reconcile_session_pair(
            session,
            owner_id=owner,
            workspace_id=DEFAULT_WORKSPACE_ID,
            provider_subject_id=pair.provider_subject_id,
            direct=pair.direct,
            relayed=pair.relayed,
            device_link=pair.device_link,
            revisions=pair.revisions,
        )
    return len(pairs)


async def _rows(session, owner: UUID) -> dict[str, tuple[str | None, bool]]:
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT normalizer_id, semantic_key, is_primary FROM canonical_observations "
            "WHERE owner_id = :owner AND status = 'active'"
        ),
        {"owner": owner},
    )
    return {row.normalizer_id: (row.semantic_key, row.is_primary) for row in result}


async def _decisions(session, owner: UUID) -> list[str]:
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT decision FROM fusion_decisions WHERE owner_id = :owner ORDER BY created_at"),
        {"owner": owner},
    )
    return [row.decision for row in result]


async def _fused_pair(factory, owner: UUID, *, activity: str = "Running"):
    from storage.timescale.observations import default_repository as canonical

    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    end = start + timedelta(minutes=45)
    whoop = _whoop_workout(owner, start, end)
    async with factory() as session:
        await canonical.insert_many(session, [whoop])
        await canonical.insert_many(
            session, [_apple_workout(owner, start, end, activity=activity, raw_ref=100)]
        )
        await _link(session, owner, whoop.stream_id, status="confirmed", confidence="strong")
        await _reconcile(session, owner)
        await session.commit()
    return whoop, start, end


@pytest.mark.asyncio
async def test_a_resent_apple_workout_keeps_its_fusion(db) -> None:
    from storage.timescale.observations import default_repository as canonical

    factory, owner = db
    whoop, start, end = await _fused_pair(factory, owner)
    async with factory() as session:
        fused = await _rows(session, owner)
    key = fused["whoop-healthsave"][0]
    assert key is not None
    assert fused == {"whoop-healthsave": (key, True), "apple_health": (key, False)}

    # The phone re-sends the same workout (same uuid, newer raw payload).
    async with factory() as session:
        await canonical.insert_many(
            session, [_apple_workout(owner, start, end, activity="Running", raw_ref=200)]
        )
        await session.commit()
        assert await _rows(session, owner) == fused, "both copies count again"
        assert await _reconcile(session, owner) == 0


@pytest.mark.asyncio
async def test_a_rejected_pair_is_decided_once(db) -> None:
    from storage.timescale.observations import default_repository as canonical

    factory, owner = db
    # The relayed copy says "cycling", the direct one "running": no fusion.
    whoop, start, end = await _fused_pair(factory, owner, activity="Cycling")
    async with factory() as session:
        for _ in range(3):  # three more polls
            assert await _reconcile(session, owner) == 0
        await session.commit()
        assert await _decisions(session, owner) == ["rejected"]

    # The phone corrects the activity: the changed row is a candidate again.
    async with factory() as session:
        await canonical.insert_many(
            session, [_apple_workout(owner, start, end, activity="Running", raw_ref=300)]
        )
        assert await _reconcile(session, owner) == 1
        await session.commit()
        assert await _decisions(session, owner) == ["rejected", "assigned"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "confidence"),
    [("rejected", "strong"), ("expired", "strong"), ("confirmed", "weak")],
)
async def test_a_link_that_stops_qualifying_unfuses_its_pairs(db, status, confidence) -> None:
    factory, owner = db
    whoop, _start, _end = await _fused_pair(factory, owner, activity="Running")

    async with factory() as session:
        await _link(session, owner, whoop.stream_id, status=status, confidence=confidence)
        await session.commit()
        assert await _rows(session, owner) == {
            "whoop-healthsave": (None, True),
            "apple_health": (None, True),
        }
        assert await _decisions(session, owner) == ["assigned", "revoked"]

        # Idempotent: saving the same link again revokes nothing new.
        await _link(session, owner, whoop.stream_id, status=status, confidence=confidence)
        await session.commit()
        assert await _decisions(session, owner) == ["assigned", "revoked"]


@pytest.mark.asyncio
async def test_a_link_past_its_valid_to_is_unfused_by_the_next_pass(db) -> None:
    """Expiry is a time, not a write: the pass before each reconciliation catches it."""
    from sqlalchemy import text
    from storage.timescale.fusion import default_repository

    factory, owner = db
    await _fused_pair(factory, owner)
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE device_identity_links SET valid_to = now() - interval '1 minute' "
                "WHERE owner_id = :owner"
            ),
            {"owner": owner},
        )
        assert await default_repository.revoke_unqualified_assignments(session, owner_id=owner) == 1
        await session.commit()
        assert await _rows(session, owner) == {
            "whoop-healthsave": (None, True),
            "apple_health": (None, True),
        }
        assert await _decisions(session, owner) == ["assigned", "revoked"]
