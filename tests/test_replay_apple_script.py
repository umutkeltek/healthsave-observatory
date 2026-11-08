"""scripts/replay_apple.py never writes one person's raw batches into another's.

``raw_ingestion_log`` has no ``owner_id``, and the script wrote every replayed
row to the default owner. On an Observatory with participant keys that moves
each participant's health data into the primary person's history. The script
now refuses when anyone besides the default owner has ingested data or holds a
key, and runs as before on a single-person Observatory.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID

import scripts.replay_apple as replay_script

PARTICIPANT = UUID("7a1d2c3e-0000-4000-8000-0000000000aa")


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Engine:
    async def dispose(self) -> None:
        return None


@pytest.fixture
def harness(monkeypatch):
    calls: list[dict] = []
    owners: set[UUID] = {DEFAULT_OWNER_ID}

    async def fake_replay(session, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            payloads_scanned=0,
            observations_produced=0,
            observations_rejected=0,
            observations_submitted=0,
        )

    async def fake_owners(session):
        return set(owners)

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/unused")
    monkeypatch.setattr(replay_script, "create_async_engine", lambda url: _Engine())
    monkeypatch.setattr(replay_script, "AsyncSession", lambda engine: _Session())
    monkeypatch.setattr(replay_script, "replay_apple_raw_payloads", fake_replay)
    monkeypatch.setattr(replay_script, "ingest_owner_ids", fake_owners, raising=False)
    return SimpleNamespace(calls=calls, owners=owners)


@pytest.mark.asyncio
async def test_replay_refuses_when_another_owner_has_data(harness):
    harness.owners.add(PARTICIPANT)

    with pytest.raises(SystemExit) as exc:
        await replay_script.run(dry_run=False, limit=10, max_pages=None)

    assert "owner" in str(exc.value.code)
    assert harness.calls == [], "nothing may be replayed into the default owner"


@pytest.mark.asyncio
async def test_replay_refuses_in_dry_run_too(harness):
    harness.owners.add(PARTICIPANT)

    with pytest.raises(SystemExit):
        await replay_script.run(dry_run=True, limit=10, max_pages=1)

    assert harness.calls == []


@pytest.mark.asyncio
async def test_single_person_observatory_replays_into_the_default_owner(harness):
    await replay_script.run(dry_run=True, limit=10, max_pages=1)

    assert [call["owner_id"] for call in harness.calls] == [DEFAULT_OWNER_ID]
