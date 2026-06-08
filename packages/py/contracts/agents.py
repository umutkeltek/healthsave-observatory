# SPDX-License-Identifier: Apache-2.0
"""Agent lifecycle primitives — the v2 autonomy plane in types.

The shape here encodes the rule from the synthesis: agents propose
typed actions, a policy layer approves/rejects, executions are
recorded, every step is append-only and inspectable. No agent
mutates user data directly; everything goes through this ledger.

Frameworks (LangGraph, Mastra, Burr) are *executors* against this
contract, never the contract itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from ._base import (
    ArtifactId,
    DecisionId,
    EventId,
    ExecutionId,
    ProposalId,
    RunId,
    V2Model,
    WithOwnership,
)


class AgentSpec(V2Model):
    """An agent's declared identity. Loaded from the plugin manifest.

    Process-level metadata, not user data — does not extend
    :class:`WithOwnership`.
    """

    plugin_id: str
    version: str
    name: str
    description: str
    triggers: list[Literal["cron", "ingest_event", "metric_threshold", "manual"]]
    capabilities: list[str]


class AgentRun(WithOwnership):
    """One execution of an agent. The aggregate root for the lifecycle."""

    id: RunId
    plugin_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: Literal["running", "completed", "failed", "cancelled"]
    trigger_kind: Literal["cron", "ingest_event", "metric_threshold", "manual"]
    trigger_metadata: dict = {}


class Observation(WithOwnership):
    """What the agent observed during a run. Append-only.

    Findings are intentionally a free-form ``dict`` to keep the
    contract stable across narrators evolving their statistical
    output shape.
    """

    id: UUID
    run_id: RunId
    captured_at: datetime
    metric: str | None = None
    findings: dict


class ActionProposal(WithOwnership):
    """An action the agent wants to take. Every state mutation begins here.

    ``capability`` references the manifest-declared capability the
    agent claims is sufficient to execute this action; the policy
    layer cross-checks.
    """

    id: ProposalId
    run_id: RunId
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


class ActionDecision(WithOwnership):
    """The policy layer's verdict on a proposal."""

    id: DecisionId
    proposal_id: ProposalId
    decided_at: datetime
    decision: Literal["approved", "rejected", "deferred"]
    decided_by: Literal["user", "policy", "auto"]
    rationale: str | None = None


class ActionExecution(WithOwnership):
    """The result of executing an approved proposal."""

    id: ExecutionId
    proposal_id: ProposalId
    decision_id: DecisionId
    executed_at: datetime
    status: Literal["succeeded", "failed", "skipped"]
    result: dict = {}
    error: str | None = None


class AgentEvent(WithOwnership):
    """One event in the agent timeline.

    Streamed over Server-Sent Events to ``apps/web``'s agent activity
    feed; persisted as the audit trail. The dashboard reads this
    shape directly via the generated TS client.
    """

    id: EventId
    run_id: RunId | None = None
    emitted_at: datetime
    kind: Literal[
        "run_started",
        "run_completed",
        "run_failed",
        "observation",
        "proposal_created",
        "proposal_approved",
        "proposal_rejected",
        "execution_succeeded",
        "execution_failed",
        "artifact_created",
    ]
    payload: dict


class AgentArtifact(WithOwnership):
    """A persisted output of an agent run — narrative, chart, plan."""

    id: ArtifactId
    run_id: RunId
    kind: Literal[
        "narrative",
        "chart_spec",
        "experiment_plan",
        "intervention_proposal",
    ]
    payload: dict
    created_at: datetime
