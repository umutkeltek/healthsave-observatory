"""Phase 7-E ``/api/v2/agents/*`` route tests.

Drives the FastAPI handlers directly (same pattern as
:mod:`tests.test_insights_routes`) with a FakeSession that records
SQL + returns queued rows — the same approach as
:mod:`tests.test_storage_agents`. This exercises both layers in one
test: the route's wire shape AND the repository's SQL.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.v2_agents import (  # noqa: E402
    DecideRequest,
    ProposalView,
    decide_proposal,
    list_proposals,
)
from storage.timescale.agents import DEFAULT_OWNER_ID  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# FakeSession — same shape as test_storage_agents
# ──────────────────────────────────────────────────────────────────────


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._next_row = None
        self._next_rows: list = []
        self.committed = False
        self.rolled_back = False
        self.execute_raises: Exception | None = None

    def queue_row(self, **attrs) -> None:
        self._next_row = SimpleNamespace(**attrs)

    def queue_rows(self, rows: list) -> None:
        self._next_rows = rows

    async def execute(self, statement, params=None):
        if self.execute_raises is not None:
            raise self.execute_raises
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        first_row = self._next_row
        rows = self._next_rows
        self._next_row = None
        self._next_rows = []
        return SimpleNamespace(
            first=lambda: first_row,
            fetchall=lambda: rows,
        )

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _proposal_row_namespace(
    *,
    idempotency_key: str | None = None,
    action_kind: str = "notify",
) -> SimpleNamespace:
    """SimpleNamespace shaped like the SELECT projection in
    ``TimescaleAgentRepository.fetch_recent_proposals``.
    """
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        proposed_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
        action_kind=action_kind,
        payload={"text": "hi"},
        rationale="anomaly severity=watch",
        capability="propose:notify",
        idempotency_key=idempotency_key,
        owner_id=DEFAULT_OWNER_ID,
        workspace_id=DEFAULT_OWNER_ID,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /api/v2/agents/proposals
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_proposals_returns_wire_shape():
    session = _FakeSession()
    session.queue_rows(
        [
            _proposal_row_namespace(idempotency_key="k1"),
            _proposal_row_namespace(idempotency_key="k2"),
        ]
    )

    response = await list_proposals(session=session, undecided_only=False, limit=10)

    assert response.count == 2
    assert response.undecided_only is False
    assert all(isinstance(p, ProposalView) for p in response.proposals)
    # Wire view drops owner/workspace ids
    dumped = response.proposals[0].model_dump()
    assert "owner_id" not in dumped
    assert "workspace_id" not in dumped
    # Limit reached the repo
    _sql, params = session.calls[-1]
    assert params["limit"] == 10


@pytest.mark.asyncio
async def test_list_proposals_undecided_only_uses_anti_join_sql():
    session = _FakeSession()
    session.queue_rows([])

    await list_proposals(session=session, undecided_only=True, limit=50)

    sql, _ = session.calls[-1]
    # The repo uses LEFT JOIN action_decisions ... WHERE d.id IS NULL.
    assert "LEFT JOIN action_decisions" in sql
    assert "d.id IS NULL" in sql


@pytest.mark.asyncio
async def test_list_proposals_empty_returns_zero_count():
    session = _FakeSession()
    session.queue_rows([])

    response = await list_proposals(session=session, undecided_only=False, limit=50)

    assert response.count == 0
    assert response.proposals == []


# ──────────────────────────────────────────────────────────────────────
# POST /api/v2/agents/proposals/{id}/decide
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_proposal_persists_and_commits():
    session = _FakeSession()
    decision_id = uuid4()
    session.queue_row(id=decision_id)
    proposal_id = uuid4()

    response = await decide_proposal(
        proposal_id=proposal_id,
        body=DecideRequest(decision="approved", rationale="looks fine"),
        session=session,
    )

    assert response.decision_id == decision_id
    assert response.decision == "approved"
    assert response.decided_by == "user"
    assert response.proposal_id == proposal_id
    sql, params = session.calls[-1]
    assert "INSERT INTO action_decisions" in sql
    assert params["decision"] == "approved"
    assert params["decided_by"] == "user"
    assert params["rationale"] == "looks fine"
    # Session committed exactly once.
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_decide_proposal_missing_proposal_id_yields_404():
    """A FK violation on action_decisions.proposal_id (no such proposal)
    surfaces as a 404. The session is rolled back so the transaction
    doesn't hold an aborted state.
    """
    session = _FakeSession()
    session.execute_raises = IntegrityError("INSERT", {}, Exception("FK violation"))

    with pytest.raises(HTTPException) as exc_info:
        await decide_proposal(
            proposal_id=uuid4(),
            body=DecideRequest(decision="rejected"),
            session=session,
        )

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_decide_request_rejects_unknown_decision_value():
    """The Literal on DecideRequest.decision rejects bogus strings at
    validation time. Phase 7-A's CHECK constraint is a backstop, but
    we want the wire layer to refuse first.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        DecideRequest(decision="thumbs_up")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_decide_proposal_optional_rationale_is_none():
    session = _FakeSession()
    session.queue_row(id=uuid4())

    await decide_proposal(
        proposal_id=uuid4(),
        body=DecideRequest(decision="deferred"),  # no rationale
        session=session,
    )

    _, params = session.calls[-1]
    assert params["rationale"] is None


# ──────────────────────────────────────────────────────────────────────
# Router wiring — make sure FastAPI picked up both routes
# ──────────────────────────────────────────────────────────────────────


def test_router_has_both_routes_registered():
    """A 7-E regression that quietly drops one route would be hard to
    catch via behavior tests. Inspect the router directly.
    """
    from server.api.v2_agents import router

    paths = {(route.path, frozenset(route.methods)) for route in router.routes}
    assert ("/api/v2/agents/proposals", frozenset({"GET"})) in paths
    assert ("/api/v2/agents/proposals/{proposal_id}/decide", frozenset({"POST"})) in paths


def test_router_uses_correct_prefix():
    """The /api/v2/ namespace is the Phase 7-E convention — v1 stays
    flat under /api/. This test pins the prefix so a future rename
    that drifts v1 vs v2 surfaces here.
    """
    from server.api.v2_agents import router

    assert router.prefix == "/api/v2/agents"
