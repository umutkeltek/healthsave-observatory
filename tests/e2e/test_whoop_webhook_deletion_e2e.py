"""E2E: a Whoop ``workout.deleted`` webhook supersedes the canonical session.

Whoop reports a deletion by its own record id; the resource can no longer be
fetched. The webhook used to fetch it anyway (a 404, answered as a 500 that
Whoop retried) and never removed the workout. Runs the real plugin and the
real canonical repository on PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


class _Http:
    async def get(self, url, *, params=None, headers=None):
        raise AssertionError(f"a deletion must not fetch {url}")


class _Tokens:
    def __init__(self, owner) -> None:
        from auth import OAuthToken

        self.token = OAuthToken(
            owner_id=owner,
            provider="whoop",
            access_token="AT",
            refresh_token="RT",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def get_token(self, session, *, provider, owner_id):
        return self.token


@pytest.mark.asyncio
async def test_a_deleted_whoop_workout_leaves_the_canonical_store() -> None:
    from plugin_sdk import find_plugin_manifest, load_manifest
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale.observations import default_repository

    from plugins.sources.whoop import WhoopSource
    from plugins.sources.whoop.normalize import canonical_session_observations

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = uuid4()
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    workouts = canonical_session_observations(
        [
            {
                "id": workout_id,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "sport_id": 0,
                "score_state": "SCORED",
                "score": {"kilojoule": 900.0},
            }
            for workout_id in ("wk-deleted", "wk-kept")
        ],
        owner_id=owner,
        provider_subject_id="whoop-user-1",
    )
    plugin = WhoopSource(load_manifest(find_plugin_manifest("whoop", kind="source")))
    try:
        async with factory() as session:
            await default_repository.insert_many(session, workouts)
            await session.commit()

        for _ in range(2):  # Whoop may send the event twice
            async with factory() as session:
                await plugin.handle_webhook(
                    {
                        "event": {"type": "workout.deleted", "id": "wk-deleted"},
                        "storage": object(),
                        "session": session,
                        "http_client": _Http(),
                        "owner_id": owner,
                        "token_store": _Tokens(owner),
                    }
                )
                await session.commit()

        async with factory() as session:
            rows = dict(
                (
                    await session.execute(
                        text(
                            "SELECT source_record_uid, status FROM canonical_observations "
                            "WHERE owner_id = :owner"
                        ),
                        {"owner": owner},
                    )
                ).all()
            )
        assert rows == {"wk-deleted": "superseded", "wk-kept": "active"}
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM canonical_observations WHERE owner_id = :owner"),
                {"owner": owner},
            )
            await session.commit()
        await engine.dispose()
