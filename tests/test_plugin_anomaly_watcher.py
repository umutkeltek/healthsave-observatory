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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.config import AgentSettings  # noqa: E402
from agents.supervisor import EnabledAgent, Observation, Supervisor  # noqa: E402
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
    """Records fetch_anomalies_after calls + returns queued rows.

    Returns them newest first (the wrong order) so the feed's own
    ascending-order guarantee is testable.
    """

    def __init__(self, rows: list[_FakeFindingRow]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    async def fetch_anomalies_after(
        self,
        session: Any,
        *,
        after=None,
        severities=None,
        limit: int = 100,
    ):
        self.calls.append(
            {
                "after": after,
                "severities": tuple(severities) if severities else None,
                "limit": limit,
            }
        )
        return sorted(self._rows, key=lambda r: r.created_at, reverse=True)

    async def fetch_anomalies_between(self, session: Any, **kwargs):
        self.window_calls = getattr(self, "window_calls", []) + [kwargs]
        return []


class _FindingsTable:
    """In-memory ``analysis_findings`` with the production read semantics.

    ``fetch_anomalies`` mirrors the dashboard query (``created_at >= since``,
    newest first, ``LIMIT``); ``fetch_anomalies_after`` mirrors the feed's
    oldest-first page (``created_at > after``, ``LIMIT`` extended to finish
    the last ``created_at`` group). Real PostgreSQL proof of the SQL lives in
    ``tests/e2e/test_anomaly_watcher_feed_e2e.py``.
    """

    def __init__(self, rows: list[_FakeFindingRow]) -> None:
        self._rows = rows

    def _matching(self, severities) -> list[_FakeFindingRow]:
        allowed = set(severities) if severities else None
        return [r for r in self._rows if allowed is None or r.severity in allowed]

    async def fetch_anomalies(self, session: Any, *, since=None, severities=None, limit=200):
        rows = [r for r in self._matching(severities) if since is None or r.created_at >= since]
        rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return rows[:limit]

    async def fetch_anomalies_after(self, session: Any, *, after=None, severities=None, limit=100):
        rows = [r for r in self._matching(severities) if after is None or r.created_at > after]
        rows.sort(key=lambda r: (r.created_at, r.id))
        if len(rows) <= limit:
            return rows
        last_created_at = rows[limit - 1].created_at
        return [r for r in rows if r.created_at <= last_created_at]

    async def fetch_anomalies_between(
        self, session: Any, *, after, until, severities=None, exclude_ids=(), limit=1000
    ):
        excluded = set(exclude_ids)
        rows = [
            r
            for r in self._matching(severities)
            if after < r.created_at <= until and r.id not in excluded
        ]
        rows.sort(key=lambda r: (r.created_at, r.id))
        return rows[:limit]


def _engine_runs(*, runs: int, per_run: int) -> list[_FakeFindingRow]:
    """Findings the way the analysis engine writes them: one run inserts all
    of its findings in one transaction, so they share one ``created_at``
    (``DEFAULT now()``). Every 5th finding is ``info`` and must never surface.
    """
    start = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    rows: list[_FakeFindingRow] = []
    for run in range(runs):
        created_at = start + timedelta(hours=run)
        for _ in range(per_run):
            finding_id = len(rows) + 1
            rows.append(
                _FakeFindingRow(
                    id=finding_id,
                    metric="heart_rate",
                    severity="info" if finding_id % 5 == 0 else "watch",
                    structured_data={"magnitude": 3.0, "direction": "up"},
                    created_at=created_at,
                )
            )
    return rows


class _ProposalLedger:
    """Minimal :class:`storage.ports.AgentRepository` for supervisor ticks.

    Dedups on ``idempotency_key`` like the partial unique index, and keeps
    every key it was asked to write so a re-fed finding is visible.
    """

    def __init__(self) -> None:
        self.attempted_keys: list[str | None] = []
        self.stored_keys: set[str] = set()

    async def start_run(self, session: Any, **_kwargs: Any):
        return uuid4()

    async def mark_run_terminal(self, session: Any, **_kwargs: Any) -> None:
        return None

    async def propose_action(self, session: Any, *, idempotency_key=None, **_kwargs: Any):
        self.attempted_keys.append(idempotency_key)
        if idempotency_key in self.stored_keys:
            return None
        self.stored_keys.add(idempotency_key)
        return uuid4()


async def _drain(rows: list[_FakeFindingRow], *, ticks: int) -> _ProposalLedger:
    """Run ``ticks`` supervisor ticks of the real anomaly watcher over ``rows``."""
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=_FindingsTable(rows),
        limit=100,
    )
    ledger = _ProposalLedger()
    ref = EnabledAgent(
        plugin_id="hdh.agents.anomaly_watcher",
        agent=_make_agent(),
        observation_feed=feed,
        settings=AgentSettings(
            plugin_id="hdh.agents.anomaly_watcher",
            tick_interval_seconds=60.0,
            timeout_seconds=5.0,
            restart_lookback_seconds=0.0,
        ),
    )
    supervisor = Supervisor(session_factory=_session_factory(), agents_repo=ledger, enabled=[ref])
    for _ in range(ticks):
        await supervisor.tick_once(ref)
    return ledger


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def commit(self) -> None:
        return None


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
    only works if observations come back in ascending order. The fake
    repo answers newest first, so the feed's own ordering is what's
    tested.
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
async def test_feed_passes_cursor_through_as_after():
    cursor = datetime(2026, 5, 12, 8, 0, tzinfo=UTC)
    repo = _FakeBriefingRepo([])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(),
        briefing_repo=repo,
    )

    await feed.fetch_since(owner_id=uuid4(), cursor=cursor)

    assert repo.calls[0]["after"] == cursor
    assert repo.calls[0]["limit"] == 100


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
# Feed + supervisor — a backlog drains without skipping (M18)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_backlog_bigger_than_one_page_drains_oldest_first_without_skipping():
    """250 findings in five engine runs of 50 (each run shares one
    ``created_at``), 200 of them watch-level, page limit 100. The pages cut
    through a run, so this also covers rows that share a timestamp across a
    page boundary.

    Before the fix the feed read the NEWEST 100, the cursor jumped to their
    max, and the 100 oldest watch findings were never observed.
    """
    rows = _engine_runs(runs=5, per_run=50)
    expected = {str(r.id) for r in rows if r.severity != "info"}
    assert len(expected) == 200

    ledger = await _drain(rows, ticks=6)

    proposed = {key.rsplit(":", 1)[1] for key in ledger.stored_keys}
    assert proposed == expected, f"{len(expected - proposed)} findings were never observed"
    # The cursor is exclusive and every page ends on a whole created_at
    # group, so no finding is fed to the agent twice.
    assert len(ledger.attempted_keys) == len(expected)


@pytest.mark.asyncio
async def test_one_run_bigger_than_a_page_is_not_stuck_on_its_shared_timestamp():
    """One engine run with 150 watch findings, all at one ``created_at``,
    and a page limit of 100. Splitting that group at the limit would leave
    either a gap (exclusive bound) or a page that never moves past the
    timestamp (inclusive bound). The page carries the whole group instead.
    """
    rows = _engine_runs(runs=1, per_run=150)
    expected = {str(r.id) for r in rows if r.severity != "info"}
    assert len(expected) == 120

    ledger = await _drain(rows, ticks=3)

    proposed = {key.rsplit(":", 1)[1] for key in ledger.stored_keys}
    assert proposed == expected, f"{len(expected - proposed)} findings were never observed"
    assert len(ledger.attempted_keys) == len(expected)


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


@pytest.mark.asyncio
async def test_a_finding_committed_late_with_an_earlier_timestamp_is_still_observed():
    """``created_at`` is the writing transaction's start. A daily briefing holds
    its transaction through the LLM call, so its findings can commit after an
    anomaly check's later-stamped ones the watcher has already passed."""
    t2 = datetime(2026, 11, 1, 6, 5, tzinfo=UTC)
    quick = _FakeFindingRow(id=2, metric="hrv", severity="alert", structured_data={}, created_at=t2)
    table = _FindingsTable([quick])
    feed = AnalysisFindingsAnomalyFeed(
        session_factory=_session_factory(), briefing_repo=table, limit=100
    )
    ledger = _ProposalLedger()
    ref = EnabledAgent(
        plugin_id="hdh.agents.anomaly_watcher",
        agent=_make_agent(),
        observation_feed=feed,
        settings=AgentSettings(
            plugin_id="hdh.agents.anomaly_watcher",
            tick_interval_seconds=60.0,
            timeout_seconds=5.0,
            restart_lookback_seconds=0.0,
        ),
    )
    supervisor = Supervisor(session_factory=_session_factory(), agents_repo=ledger, enabled=[ref])
    await supervisor.tick_once(ref)
    assert ref.cursor == t2

    # The briefing's finding, stamped two minutes earlier, commits now.
    late = _FakeFindingRow(
        id=1,
        metric="heart_rate",
        severity="watch",
        structured_data={},
        created_at=t2 - timedelta(minutes=2),
    )
    table._rows.append(late)
    await supervisor.tick_once(ref)
    await supervisor.tick_once(ref)

    assert {key.rsplit(":", 1)[-1] for key in ledger.stored_keys} == {"1", "2"}
    assert ref.cursor == t2, "the cursor never moves back"
    # Each finding is fed once: an acknowledged late row is not re-observed.
    assert sorted(ledger.attempted_keys, key=str) == sorted(ledger.stored_keys, key=str)
