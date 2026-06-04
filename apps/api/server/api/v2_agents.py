"""GET/POST ``/api/v2/agents/*`` — Phase 7-E proposal review surface.

First route under the ``/api/v2/`` namespace. v1 surfaces (under
``/api/`` flat) continue unchanged; v2 is where the agent autonomy
plane (ledger, proposals, decisions, executions) lives — none of
which existed when the v1 contract froze.

Two endpoints:

  * ``GET  /api/v2/agents/proposals`` — list recent proposals; pass
    ``undecided_only=true`` to show only the ones awaiting an operator
    decision (the supervisor's dashboard default).
  * ``POST /api/v2/agents/proposals/{proposal_id}/decide`` — operator
    approves / rejects / defers one proposal. ``decided_by`` is hard-
    coded to ``"user"`` for Phase 7-E; future auto-approval policy
    paths will set ``"policy"`` / ``"auto"`` and pass through the same
    repository method.

Discipline:

  * Reads / writes go through :class:`storage.ports.AgentRepository`, never raw
    SQL.
  * Wire shapes are :class:`V2Model` subclasses defined inline — the
    contracts module's ``ActionProposal`` carries owner/workspace ids
    which are single-user sentinels here; the wire shape drops them
    so the response stays homelab-friendly. Phase 9+ multi-tenant
    work surfaces the ids when they become meaningful.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from contracts._base import V2Model
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import agent_repository
from storage.ports import AgentRepository

from .deps import get_session, verify_api_key

_log = logging.getLogger("healthsave.api.v2_agents")
_AGENT_REPO: AgentRepository = agent_repository()


# ──────────────────────────────────────────────────────────────────────
# Wire models
# ──────────────────────────────────────────────────────────────────────


class ProposalView(V2Model):
    """One proposal as it appears on the wire.

    Single-user-mode drops ``owner_id`` + ``workspace_id`` — they're
    sentinel UUIDs on every row and add noise. Phase 9+ multi-tenant
    work re-surfaces them. ``decided`` is a convenience flag so
    dashboards can render decision status without joining client-side.
    """

    id: UUID
    run_id: UUID
    proposed_at: datetime
    action_kind: Literal[
        "notify",
        "create_experiment",
        "create_briefing",
        "request_user_input",
        "tag_measurement",
    ]
    payload: dict
    rationale: str
    capability: str
    idempotency_key: str | None = None


class ProposalsListResponse(V2Model):
    proposals: list[ProposalView]
    undecided_only: bool
    count: int


class DecideRequest(V2Model):
    """Operator's decision on one proposal.

    ``rationale`` is optional but encouraged — Phase 7-E's audit trail
    is the same ledger that Phase 7-A laid down; an unexplained
    rejection is a near-future regret. The UI should default-prompt.
    """

    decision: Literal["approved", "rejected", "deferred"]
    rationale: str | None = Field(default=None, max_length=2000)


class DecideResponse(V2Model):
    proposal_id: UUID
    decision_id: UUID
    decision: Literal["approved", "rejected", "deferred"]
    decided_by: Literal["user", "policy", "auto"]


# ──────────────────────────────────────────────────────────────────────
# Mapping helpers
# ──────────────────────────────────────────────────────────────────────


def _row_to_view(row: Any) -> ProposalView:
    """Storage projection → wire view. Drops owner/workspace sentinels."""
    return ProposalView(
        id=row.id,
        run_id=row.run_id,
        proposed_at=row.proposed_at,
        action_kind=row.action_kind,
        payload=row.payload,
        rationale=row.rationale,
        capability=row.capability,
        idempotency_key=row.idempotency_key,
    )


# ──────────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────────


router = APIRouter(
    prefix="/api/v2/agents",
    dependencies=[Depends(verify_api_key)],
    tags=["v2-agents"],
)


@router.get("/proposals", response_model=ProposalsListResponse)
async def list_proposals(
    session: AsyncSession = Depends(get_session),
    undecided_only: bool = Query(
        default=False,
        description=(
            "When true, only return proposals without a matching action_decisions row. "
            "The dashboard's review queue uses this; full audit views set false."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> ProposalsListResponse:
    """List recent proposals.

    Reads through the agent repository. Per the Phase 5 storage-zone rule, the
    route never composes its own query against ``action_proposals``.
    """
    rows = await _AGENT_REPO.fetch_recent_proposals(
        session,
        limit=limit,
        undecided_only=undecided_only,
    )
    return ProposalsListResponse(
        proposals=[_row_to_view(r) for r in rows],
        undecided_only=undecided_only,
        count=len(rows),
    )


@router.post(
    "/proposals/{proposal_id}/decide",
    response_model=DecideResponse,
    status_code=201,
)
async def decide_proposal(
    proposal_id: UUID,
    body: DecideRequest,
    session: AsyncSession = Depends(get_session),
) -> DecideResponse:
    """Record the operator's decision on one proposal.

    Writes a single row into ``action_decisions`` via
    :class:`storage.ports.AgentRepository`. The decision is append-only —
    re-deciding (e.g. flipping a rejection to an
    approval) writes a new row, and downstream readers take the
    newest. The supervisor / executor path that picks up an approved
    proposal is Phase 7-F territory; Phase 7-E only persists the
    decision.

    Errors:

      * ``404`` — no proposal with that id. We intentionally don't
        leak whether the id is malformed-but-syntactically-valid vs.
        truly absent; both surface as 404.
    """
    try:
        decision_id = await _AGENT_REPO.decide_action(
            session,
            proposal_id=proposal_id,
            decision=body.decision,
            decided_by="user",
            rationale=body.rationale,
        )
    except IntegrityError as exc:
        # FK violation on action_decisions.proposal_id → no such proposal.
        # Other IntegrityError paths (e.g. an enum check failing) would
        # also land here; that's acceptable for v0 — both reduce to
        # "the operator handed us bad data."
        await session.rollback()
        raise HTTPException(status_code=404, detail="proposal not found") from exc

    await session.commit()

    return DecideResponse(
        proposal_id=proposal_id,
        decision_id=decision_id,
        decision=body.decision,
        decided_by="user",
    )


__all__ = [
    "router",
    "ProposalView",
    "ProposalsListResponse",
    "DecideRequest",
    "DecideResponse",
]
