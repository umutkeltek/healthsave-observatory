"""Phase 7-B AgentRepository tests.

Covers the SQL shape every method emits via a FakeSession that
records (sql, params) tuples. The production
``PostgresAgentRepository`` is the same pass-through wrapper as the
other Timescale repos — proving the SQL shape via FakeSession is
the same coverage strategy as ``test_storage_protocol.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.ports import AgentRepository  # noqa: E402
from storage.timescale.agents import (  # noqa: E402
    DEFAULT_OWNER_ID,
    ProposalRow,
    TimescaleAgentRepository,
    decide_action,
    default_repository,
    execute_action,
    fetch_recent_proposals,
    mark_run_terminal,
    propose_action,
    record_artifact,
    record_event,
    start_run,
)

# ──────────────────────────────────────────────────────────────────────
# FakeSession — records every execute() so tests can assert SQL shape
# ──────────────────────────────────────────────────────────────────────


class _FakeSession:
    """Records SQL + params. ``execute()`` returns a result whose
    ``first()`` yields the configured row (an object with the
    attribute names the SQL's RETURNING / SELECT projects).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._next_row = None
        self._next_rows: list = []

    def queue_row(self, **attrs) -> None:
        """Set what the NEXT .first() call returns."""
        self._next_row = SimpleNamespace(**attrs)

    def queue_rows(self, rows: list) -> None:
        """Set what the NEXT .fetchall() call returns."""
        self._next_rows = rows

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        first_row = self._next_row
        rows = self._next_rows
        # Reset between calls so each test queues precisely what it needs.
        self._next_row = None
        self._next_rows = []
        return SimpleNamespace(
            first=lambda: first_row,
            fetchall=lambda: rows,
        )

    def last_call(self) -> tuple[str, dict]:
        return self.calls[-1]


# ──────────────────────────────────────────────────────────────────────
# Protocol shape
# ──────────────────────────────────────────────────────────────────────


def test_postgres_agent_repository_implements_protocol():
    """Liskov: the Timescale impl is a structural AgentRepository."""
    assert isinstance(TimescaleAgentRepository(), AgentRepository)
    assert isinstance(default_repository, AgentRepository)


# ──────────────────────────────────────────────────────────────────────
# Runs
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_run_inserts_with_running_status_and_returns_id():
    session = _FakeSession()
    new_id = uuid4()
    session.queue_row(id=new_id)

    returned = await start_run(session, plugin_id="anomaly-watcher", trigger_kind="ingest_event")

    assert returned == new_id
    sql, params = session.last_call()
    assert "INSERT INTO agent_runs" in sql
    assert "'running'" in sql
    assert params["plugin_id"] == "anomaly-watcher"
    assert params["trigger_kind"] == "ingest_event"
    # trigger_metadata defaults to empty dict serialized.
    assert json.loads(params["trigger_metadata"]) == {}
    assert UUID(params["owner_id"]) == DEFAULT_OWNER_ID


@pytest.mark.asyncio
async def test_mark_run_terminal_rejects_running_status():
    """Terminal means terminal — passing 'running' is a contract bug."""
    session = _FakeSession()
    with pytest.raises(ValueError):
        await mark_run_terminal(session, run_id=uuid4(), status="running")
    assert session.calls == []  # no SQL emitted


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_mark_run_terminal_updates_status_and_ended_at(status):
    session = _FakeSession()
    run_id = uuid4()

    await mark_run_terminal(session, run_id=run_id, status=status)

    sql, params = session.last_call()
    assert "UPDATE agent_runs" in sql
    assert "ended_at = now()" in sql
    assert params["status"] == status
    assert UUID(params["run_id"]) == run_id


# ──────────────────────────────────────────────────────────────────────
# Proposals — idempotency-aware
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_action_returns_id_on_fresh_insert():
    session = _FakeSession()
    new_id = uuid4()
    session.queue_row(id=new_id)

    returned = await propose_action(
        session,
        run_id=uuid4(),
        action_kind="notify",
        payload={"text": "elevated HRV"},
        rationale="hrv anomaly severity=watch",
        capability="propose:notify",
        idempotency_key="anomaly-watcher:finding-123",
    )

    assert returned == new_id
    sql, params = session.last_call()
    assert "INSERT INTO action_proposals" in sql
    assert "ON CONFLICT (idempotency_key)" in sql
    assert "WHERE idempotency_key IS NOT NULL" in sql
    assert "DO NOTHING" in sql
    assert params["idempotency_key"] == "anomaly-watcher:finding-123"
    assert json.loads(params["payload"]) == {"text": "elevated HRV"}


@pytest.mark.asyncio
async def test_propose_action_returns_none_when_idempotency_conflicts():
    """ON CONFLICT DO NOTHING + no RETURNING row → caller sees None
    and treats as 'already proposed; do not re-emit downstream events.'
    """
    session = _FakeSession()
    # Don't queue a row — execute() returns first()==None, matching
    # what Postgres does when the INSERT was a no-op.

    returned = await propose_action(
        session,
        run_id=uuid4(),
        action_kind="notify",
        payload={"text": "duplicate"},
        rationale="duplicate proposal",
        capability="propose:notify",
        idempotency_key="anomaly-watcher:finding-123",
    )

    assert returned is None
    sql, _ = session.last_call()
    assert "INSERT INTO action_proposals" in sql


@pytest.mark.asyncio
async def test_propose_action_idempotency_key_is_optional():
    """Manual proposals + future kinds don't need an idempotency_key.
    The SQL passes NULL in that case; the partial unique index ignores
    NULLs so multiple un-keyed proposals coexist.
    """
    session = _FakeSession()
    session.queue_row(id=uuid4())

    await propose_action(
        session,
        run_id=uuid4(),
        action_kind="create_briefing",
        payload={},
        rationale="manual",
        capability="propose:create_briefing",
    )

    _, params = session.last_call()
    assert params["idempotency_key"] is None


# ──────────────────────────────────────────────────────────────────────
# Decisions, Executions, Events, Artifacts
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_action_returns_decision_id():
    session = _FakeSession()
    new_id = uuid4()
    session.queue_row(id=new_id)

    returned = await decide_action(
        session,
        proposal_id=uuid4(),
        decision="approved",
        decided_by="user",
        rationale="reviewed in dashboard",
    )

    assert returned == new_id
    sql, params = session.last_call()
    assert "INSERT INTO action_decisions" in sql
    assert params["decision"] == "approved"
    assert params["decided_by"] == "user"
    assert params["rationale"] == "reviewed in dashboard"


@pytest.mark.asyncio
async def test_execute_action_returns_execution_id_with_result_json():
    session = _FakeSession()
    new_id = uuid4()
    session.queue_row(id=new_id)

    returned = await execute_action(
        session,
        proposal_id=uuid4(),
        decision_id=uuid4(),
        status="succeeded",
        result={"delivered_to": "user@example.com"},
    )

    assert returned == new_id
    sql, params = session.last_call()
    assert "INSERT INTO action_executions" in sql
    assert params["status"] == "succeeded"
    assert json.loads(params["result"]) == {"delivered_to": "user@example.com"}


@pytest.mark.asyncio
async def test_record_event_accepts_null_run_id():
    """Some events (e.g. supervisor-level, not tied to one run) carry
    no run_id. Schema allows NULL; the repo must propagate it.
    """
    session = _FakeSession()
    session.queue_row(id=uuid4())

    await record_event(session, run_id=None, kind="run_started", payload={"trigger": "boot"})

    sql, params = session.last_call()
    assert "INSERT INTO agent_events" in sql
    assert params["run_id"] is None
    assert params["kind"] == "run_started"


@pytest.mark.asyncio
async def test_record_artifact_persists_payload_as_json():
    session = _FakeSession()
    session.queue_row(id=uuid4())

    await record_artifact(
        session,
        run_id=uuid4(),
        kind="narrative",
        payload={"chunks": ["hello", "world"]},
    )

    sql, params = session.last_call()
    assert "INSERT INTO agent_artifacts" in sql
    assert params["kind"] == "narrative"
    assert json.loads(params["payload"]) == {"chunks": ["hello", "world"]}


# ──────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────


def _proposal_row(idempotency_key: str | None = None):
    """Build a SimpleNamespace shaped like the SELECT projection."""
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        proposed_at=__import__("datetime").datetime(2026, 5, 11, 12, 0),
        action_kind="notify",
        payload={"text": "elevated HRV"},
        rationale="hrv anomaly",
        capability="propose:notify",
        idempotency_key=idempotency_key,
        owner_id=DEFAULT_OWNER_ID,
        workspace_id=DEFAULT_OWNER_ID,
    )


@pytest.mark.asyncio
async def test_fetch_recent_proposals_returns_proposal_rows():
    session = _FakeSession()
    fake_rows = [_proposal_row("k1"), _proposal_row("k2")]
    session.queue_rows(fake_rows)

    rows = await fetch_recent_proposals(session, limit=10)

    assert len(rows) == 2
    assert all(isinstance(r, ProposalRow) for r in rows)
    sql, params = session.last_call()
    # Default path (no undecided_only) hits the simple SELECT, not the JOIN.
    assert "LEFT JOIN action_decisions" not in sql
    assert params["limit"] == 10


@pytest.mark.asyncio
async def test_fetch_recent_proposals_undecided_only_uses_anti_join():
    """The Phase 7-E /decide route shows only proposals without a
    decision row. The LEFT JOIN + WHERE d.id IS NULL is the anti-join.
    """
    session = _FakeSession()
    session.queue_rows([])

    await fetch_recent_proposals(session, undecided_only=True)

    sql, _ = session.last_call()
    assert "LEFT JOIN action_decisions d ON d.proposal_id = p.id" in sql
    assert "WHERE p.owner_id = :owner_id" in sql
    assert "AND d.id IS NULL" in sql


@pytest.mark.asyncio
async def test_fetch_recent_proposals_handles_serialized_payload():
    """Some drivers return JSONB as already-decoded dict, others as
    string. The repo must tolerate both — the production asyncpg
    driver returns dict; the FakeSession uses dict for simplicity.
    """
    session = _FakeSession()
    # Mix one dict payload and one string-serialized payload to cover
    # both branches.
    row_dict = _proposal_row("k1")
    row_str = _proposal_row("k2")
    row_str.payload = '{"text": "from-string"}'
    session.queue_rows([row_dict, row_str])

    rows = await fetch_recent_proposals(session, limit=10)
    assert rows[0].payload == {"text": "elevated HRV"}
    assert rows[1].payload == {"text": "from-string"}
