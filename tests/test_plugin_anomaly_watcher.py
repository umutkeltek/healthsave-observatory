"""Phase 7-D anomaly-watcher plugin tests.

Two surfaces:

  1. :class:`AnomalyWatcherAgent` — pure decision logic. Observe one
     event per call; propose one notify per observed event; clear the
     queue at the start of propose.
  2. :class:`AnalysisFindingsAnomalyFeed` — concrete observation feed.
     Reads through :class:`storage.ports.BriefingRepository`, converts
     :class:`FindingRow` to :class:`Observation`, returns in ascending
     ``created_at`` order.

A third smoke check confirms the manifest is well-formed and the
plugin loads via :func:`plugin_sdk.load_plugin` — the same path the
supervisor uses at startup.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.supervisor import Observation  # noqa: E402
from plugin_sdk import Agent, PluginManifest, load_plugin  # noqa: E402

from plugins.agents.anomaly_watcher import AnomalyWatcherAgent  # noqa: E402
from plugins.agents.anomaly_watcher.feed import (  # noqa: E402
    DEFAULT_SEVERITIES,
    AnalysisFindingsAnomalyFeed,
)

# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


def _make_agent() -> AnomalyWatcherAgent:
    """Build an AnomalyWatcherAgent without going through the loader."""
    manifest = PluginManifest(
        id="hdh.agents.anomaly_watcher",
        name="Anomaly Watcher",
        kind="agent",
        version="0.1.0",
        sdk_version="*",
        entrypoint="plugins.agents.anomaly_watcher:AnomalyWatcherAgent",
    )
    return AnomalyWatcherAgent(manifest)


@dataclass
class _FakeFindingRow:
    id: int
    metric: str | None
    severity: str | None
    structured_data: dict[str, Any]
    created_at: datetime


class _FakeBriefingRepo:
    """Records fetch_anomalies calls + returns queued rows.

    Reverses the default 'newest first' the production repo returns so
    the feed's ascending-order contract is testable.
    """

    def __init__(self, rows: list[_FakeFindingRow]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    async def fetch_anomalies(
        self,
        session: Any,
        *,
        since=None,
        severities=None,
        limit: int = 200,
    ):
        self.calls.append(
            {
                "since": since,
                "severities": tuple(severities) if severities else None,
                "limit": limit,
            }
        )
        # Mirror production: newest-first. The feed reorders.
        return sorted(self._rows, key=lambda r: r.created_at, reverse=True)


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _session_factory():
    @asynccontextmanager
    async def factory():
        yield _FakeSession()

    return factory


# ──────────────────────────────────────────────────────────────────────
# AnomalyWatcherAgent — decision logic
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_proposes_one_notify_per_observation():
    agent = _make_agent()
    await agent.observe(
        {
            "finding_id": "42",
            "metric": "heart_rate",
            "severity": "watch",
            "structured_data": {"magnitude": 2.5, "direction": "up"},
        }
    )
    await agent.observe(
        {
            "finding_id": "43",
            "metric": "hrv",
            "severity": "alert",
            "structured_data": {"magnitude": 3.2, "direction": "down"},
        }
    )

    proposals = await agent.propose()

    assert [p["subject_id"] for p in proposals] == ["42", "43"]
    assert all(p["action_kind"] == "notify" for p in proposals)
    assert all(p["capability"] == "propose:notify" for p in proposals)
    # ── Body is built from structured magnitude + direction
    assert "2.5" in proposals[0]["payload"]["body"]
    assert "up" in proposals[0]["payload"]["body"]


@pytest.mark.asyncio
async def test_agent_propose_clears_pending_queue():
    """Each tick is one decision round — propose() must reset the queue
    so the next tick doesn't re-emit yesterday's proposals.
    """
    agent = _make_agent()
    await agent.observe(
        {"finding_id": "1", "metric": "x", "severity": "watch", "structured_data": {}}
    )
    first = await agent.propose()
    assert len(first) == 1

    # No new observe — propose should produce zero, NOT re-emit the previous.
    second = await agent.propose()
    assert second == []


@pytest.mark.asyncio
async def test_agent_handles_missing_finding_id_as_none_subject():
    """Without a finding_id, subject_id is None — the supervisor will
    then write the proposal with idempotency_key=None (always lands).
    """
    agent = _make_agent()
    await agent.observe({"metric": "heart_rate", "severity": "watch", "structured_data": {}})
    proposals = await agent.propose()
    assert proposals[0]["subject_id"] is None


@pytest.mark.asyncio
async def test_agent_handles_missing_structured_data_gracefully():
    """Some findings won't carry magnitude/direction — the body falls
    back to a generic line instead of crashing.
    """
    agent = _make_agent()
    await agent.observe(
        {"finding_id": "1", "metric": "sleep", "severity": "watch", "structured_data": {}}
    )
    proposals = await agent.propose()
    assert "anomaly" in proposals[0]["payload"]["body"].lower()


# ──────────────────────────────────────────────────────────────────────
# AnalysisFindingsAnomalyFeed — storage seam
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feed_filters_to_default_severities_watch_and_alert():
    """``info`` is the 'noted but not actionable' tier — the feed's
    default allowlist excludes it so the agent never emits notifies
    for low-signal anomalies.
    """
    repo = _FakeBriefingRepo([])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
    )

    await feed.fetch_since(owner_id=uuid4(), cursor=None)

    assert repo.calls[0]["severities"] == DEFAULT_SEVERITIES
    assert DEFAULT_SEVERITIES == ("watch", "alert")


@pytest.mark.asyncio
async def test_feed_returns_observations_in_ascending_created_at_order():
    """Supervisor advances its cursor as ``max(occurred_at)``. That
    only works if observations come back in ascending order — the
    production briefings repo returns newest-first, so the feed must
    reorder.
    """
    rows = [
        _FakeFindingRow(
            id=1,
            metric="heart_rate",
            severity="watch",
            structured_data={"magnitude": 2.5, "direction": "up"},
            created_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        ),
        _FakeFindingRow(
            id=2,
            metric="hrv",
            severity="alert",
            structured_data={"magnitude": 3.0, "direction": "down"},
            created_at=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        ),
    ]
    repo = _FakeBriefingRepo(rows)
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
    )

    observations = await feed.fetch_since(owner_id=uuid4(), cursor=None)

    # row id=2 is earlier in time; should appear first.
    assert [o.subject_id for o in observations] == ["2", "1"]
    assert all(isinstance(o, Observation) for o in observations)
    # Ascending check
    assert observations[0].occurred_at < observations[1].occurred_at


@pytest.mark.asyncio
async def test_feed_passes_cursor_through_as_since():
    cursor = datetime(2026, 5, 12, 8, 0, tzinfo=UTC)
    repo = _FakeBriefingRepo([])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
    )

    await feed.fetch_since(owner_id=uuid4(), cursor=cursor)

    assert repo.calls[0]["since"] == cursor


@pytest.mark.asyncio
async def test_feed_observation_payload_carries_finding_metadata():
    row = _FakeFindingRow(
        id=42,
        metric="heart_rate",
        severity="watch",
        structured_data={"magnitude": 2.7},
        created_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
    )
    repo = _FakeBriefingRepo([row])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
    )

    [observation] = await feed.fetch_since(owner_id=uuid4(), cursor=None)
    assert observation.subject_id == "42"
    assert observation.payload["finding_id"] == "42"
    assert observation.payload["metric"] == "heart_rate"
    assert observation.payload["severity"] == "watch"
    assert observation.payload["structured_data"] == {"magnitude": 2.7}


@pytest.mark.asyncio
async def test_feed_severity_allowlist_is_overridable():
    """Operators tuning sensitivity may want ``info`` surfaced (or just
    ``alert``). The feed accepts an explicit override.
    """
    repo = _FakeBriefingRepo([])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
        severities=("alert",),
    )

    await feed.fetch_since(owner_id=uuid4(), cursor=None)
    assert repo.calls[0]["severities"] == ("alert",)


# ──────────────────────────────────────────────────────────────────────
# Manifest + loader smoke test
# ──────────────────────────────────────────────────────────────────────


def test_anomaly_watcher_loads_via_plugin_sdk():
    """End-to-end smoke check: the manifest under
    ``plugins/agents/anomaly_watcher/plugin.yaml`` discovers, passes
    sdk_version, resolves its entrypoint, and the resulting object is
    an Agent subclass. This is the same path the supervisor takes at
    startup.
    """
    plugin = load_plugin("hdh.agents.anomaly_watcher", kind="agent")
    assert isinstance(plugin, Agent)
    assert isinstance(plugin, AnomalyWatcherAgent)
