"""E2E: one proposal PostgreSQL rejects cannot wedge an agent (M18).

The supervisor writes every proposal of a tick in one transaction and only
moves its cursor after the commit. Before the fix, a single proposal that
``action_proposals`` rejects (unknown ``action_kind``, NULL rationale, NUL or
NaN in the payload, ...) failed that transaction on every tick: the cursor
never moved and the agent re-proposed the same thing forever.

The first test proves on real PostgreSQL that each of those shapes really is
rejected by the table, and that :func:`agents.supervisor.proposal_problem`
names every one of them. The second runs a real supervisor tick against the
real repository and checks the good proposal lands and the cursor moves.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


def _good(subject_id: str) -> dict[str, Any]:
    return {
        "action_kind": "notify",
        "payload": {"title": "HRV anomaly (watch)", "magnitude": 3.1},
        "rationale": "anomaly severity=watch on hrv",
        "capability": "propose:notify",
        "subject_id": subject_id,
    }


def _bad(subject_id: str, **changes: Any) -> dict[str, Any]:
    return {**_good(subject_id), **changes}


REJECTED_BY_POSTGRES = {
    "unknown action_kind": {"action_kind": "send_email"},
    "null rationale": {"rationale": None},
    "null capability": {"capability": None},
    "NUL in rationale": {"rationale": "hrv\x00"},
    "NUL in capability": {"capability": "propose:notify\x00"},
    "NaN in payload": {"payload": {"magnitude": float("nan")}},
    "Infinity in payload": {"payload": {"magnitude": float("inf")}},
    "NUL in payload": {"payload": {"title": "hrv\x00"}},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", REJECTED_BY_POSTGRES.values(), ids=REJECTED_BY_POSTGRES)
async def test_postgres_rejects_what_proposal_problem_names(changes: dict[str, Any]) -> None:
    from agents.supervisor import proposal_problem
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.agents import default_repository as repo

    proposal = _bad(f"e2e-{uuid4().hex}", **changes)
    assert proposal_problem(proposal) is not None
    assert proposal_problem(_good("e2e-good")) is None

    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            run_id = await repo.start_run(
                session, plugin_id=f"e2e-{uuid4().hex}", trigger_kind="cron"
            )
            with pytest.raises(Exception):  # noqa: B017 - IntegrityError or DataError
                await repo.propose_action(
                    session,
                    run_id=run_id,
                    action_kind=proposal["action_kind"],
                    payload=proposal["payload"],
                    rationale=proposal["rationale"],
                    capability=proposal["capability"],
                    idempotency_key=proposal["subject_id"],
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_rejected_proposal_does_not_hold_the_cursor_on_real_postgres() -> None:
    from agents.config import AgentSettings
    from agents.supervisor import EnabledAgent, Observation, Supervisor
    from plugin_sdk import Agent, PluginManifest
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    plugin_id = f"e2e-wedge-{uuid4().hex[:12]}"

    class EchoAgent(Agent):
        def __init__(self) -> None:
            super().__init__(
                PluginManifest(
                    id=plugin_id,
                    name=plugin_id,
                    kind="agent",
                    version="0.0.1",
                    sdk_version="*",
                    entrypoint="x.y:Z",
                )
            )
            self._pending: list[dict[str, Any]] = []

        async def observe(self, event: dict[str, Any]) -> None:
            self._pending.append(event["proposal"])

        async def propose(self) -> list[dict[str, Any]]:
            pending, self._pending = self._pending, []
            return pending

    t0 = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    observations = [
        Observation(f"bad-{name}", t0 + timedelta(seconds=i), {"proposal": _bad(f"bad-{i}", **c)})
        for i, (name, c) in enumerate(REJECTED_BY_POSTGRES.items())
    ]
    observations.append(
        Observation("good", t0 + timedelta(minutes=5), {"proposal": _good("finding-good")})
    )

    class CursorFeed:
        async def fetch_since(self, *, owner_id, cursor):
            return [o for o in observations if cursor is None or o.occurred_at > cursor]

    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ref = EnabledAgent(
        plugin_id=plugin_id,
        agent=EchoAgent(),
        observation_feed=CursorFeed(),
        settings=AgentSettings(
            plugin_id=plugin_id,
            tick_interval_seconds=60.0,
            timeout_seconds=10.0,
            restart_lookback_seconds=0.0,
        ),
    )
    supervisor = Supervisor(session_factory=session_factory, enabled=[ref])
    try:
        await supervisor.tick_once(ref)

        assert ref.cursor == observations[-1].occurred_at
        async with session_factory() as session:
            stored = (
                await session.execute(
                    text(
                        "SELECT p.idempotency_key, r.status FROM action_proposals p "
                        "JOIN agent_runs r ON r.id = p.run_id WHERE r.plugin_id = :plugin_id"
                    ),
                    {"plugin_id": plugin_id},
                )
            ).all()
        assert [tuple(row) for row in stored] == [(f"{plugin_id}:notify:finding-good", "completed")]
    finally:
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM agent_runs WHERE plugin_id = :plugin_id"),
                {"plugin_id": plugin_id},
            )
            await session.commit()
        await engine.dispose()
