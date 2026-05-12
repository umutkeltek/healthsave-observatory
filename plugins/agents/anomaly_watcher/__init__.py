"""Anomaly Watcher — first first-party Agent plugin (Phase 7-D).

Watches ``analysis_findings`` for ``finding_type='anomaly'`` events at
severity ``watch`` or above, and proposes a ``notify`` action per
finding. The decision belongs to the operator (Phase 7-E surfaces the
proposal via ``/api/v2/agents/proposals``); the agent does NOT deliver
notifications itself.

Two pieces:

  * :class:`AnomalyWatcherAgent` — pure decision logic. Receives one
    observation per :meth:`observe` call, holds them as `_pending`,
    and turns the queue into proposals in :meth:`propose`. Resetting
    the queue at the start of :meth:`propose` is intentional — each
    tick is one decision round.

  * :class:`AnalysisFindingsAnomalyFeed` (in :mod:`.feed`) — concrete
    :class:`agents.supervisor.ObservationFeed`. Reads anomaly findings
    via :class:`storage.ports.BriefingRepository`, converts each
    :class:`storage.timescale.briefings.FindingRow` to an
    :class:`agents.supervisor.Observation`, returns them in ascending
    ``created_at`` order so the supervisor's
    ``max(occurred_at)`` cursor advance is correct.

The plugin manifest declares two capabilities: ``read:analysis_findings``
and ``propose:notify``. Both are part of the contract — Phase 7-E's
``decide`` route checks the proposal's recorded capability against an
allowlist before executing.

Boundary: this plugin does NOT import from ``apps/api/server.*`` —
enforced by :mod:`tests.contract.test_apps_agents_boundary`. The only
storage import is via :class:`storage.ports.BriefingRepository`
through the feed.
"""

from __future__ import annotations

import logging
from typing import Any

from plugin_sdk import Agent

log = logging.getLogger("healthsave.plugins.anomaly_watcher")


class AnomalyWatcherAgent(Agent):
    """Per-tick: collect anomaly observations, propose one notify per.

    Observation payload shape (produced by
    :class:`AnalysisFindingsAnomalyFeed`)::

        {
            "finding_id": "42",
            "metric": "heart_rate",
            "severity": "watch",
            "structured_data": {"magnitude": 3.1, ...},
        }

    Proposal shape (emitted to :meth:`storage.ports.AgentRepository.propose_action`
    through the supervisor)::

        {
            "action_kind": "notify",
            "payload": {
                "title": "Heart rate anomaly (watch)",
                "body": "...",
                "metric": "heart_rate",
                "severity": "watch",
            },
            "rationale": "anomaly severity=watch on heart_rate",
            "capability": "propose:notify",
            "subject_id": "42",            # finding id; idempotency key suffix
        }
    """

    def __init__(self, manifest):
        super().__init__(manifest)
        self._pending: list[dict[str, Any]] = []

    async def observe(self, event: dict[str, Any]) -> None:
        """Queue one anomaly observation for the next :meth:`propose`.

        The supervisor calls ``observe`` once per observation returned
        by the feed in a given tick. The agent's queue lives only
        within the tick — :meth:`propose` clears it.
        """
        self._pending.append(event)

    async def propose(self) -> list[dict[str, Any]]:
        """Turn the queue into one notify proposal per observation, clear
        the queue, return the proposals.

        The supervisor derives idempotency keys as
        ``f"{plugin_id}:{action_kind}:{subject_id}"`` — duplicate
        re-processing of the same finding produces the same key and
        the database's partial unique index dedups.
        """
        pending, self._pending = self._pending, []
        proposals: list[dict[str, Any]] = []
        for event in pending:
            finding_id = event.get("finding_id")
            metric = event.get("metric") or "unknown"
            severity = event.get("severity") or "watch"
            structured = event.get("structured_data") or {}
            proposals.append(
                {
                    "action_kind": "notify",
                    "payload": {
                        "title": f"{_pretty_metric(metric)} anomaly ({severity})",
                        "body": _build_body(metric, severity, structured),
                        "metric": metric,
                        "severity": severity,
                        "structured_data": structured,
                    },
                    "rationale": f"anomaly severity={severity} on {metric}",
                    "capability": "propose:notify",
                    "subject_id": str(finding_id) if finding_id is not None else None,
                }
            )
        return proposals


def _pretty_metric(metric: str) -> str:
    """``heart_rate`` → ``Heart rate``. Cosmetic only — the metric name
    is the underlying identity.
    """
    return metric.replace("_", " ").capitalize()


def _build_body(metric: str, severity: str, structured: dict[str, Any]) -> str:
    """One-line summary for the notification body.

    Keep it short — notification surfaces (push, SMS, email subject)
    tend to truncate. Structured data is preserved in the proposal
    payload for richer downstream rendering.
    """
    magnitude = structured.get("magnitude")
    direction = structured.get("direction")
    if magnitude is not None and direction is not None:
        return (
            f"{_pretty_metric(metric)} reading deviated "
            f"{direction} by {abs(float(magnitude)):.1f}σ ({severity})."
        )
    return f"{_pretty_metric(metric)} showed an anomaly ({severity})."


__all__ = ["AnomalyWatcherAgent"]
