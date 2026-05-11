"""Phase 7-C supervisor tests.

Covers the 8 named scenarios from the design review:

  1. ``enabled=[]`` starts and idles
  2. Unknown enabled agent fails startup
  3. Agent observe timeout is isolated (other agents continue)
  4. Agent propose timeout is isolated
  5. ``persist_proposal`` failure does NOT advance cursor
  6. Duplicate finding does NOT create duplicate proposal
  7. Idempotency key includes action_kind
  8. Successful tick advances cursor and bumps no counter

The supervisor's I/O surface is small: a session factory, an
``AgentRepository`` Protocol, and an ``ObservationFeed`` Protocol per
agent. Tests inject fakes for all three — no live DB, no real plugin
discovery, no asyncio.sleep ticks.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.config import (  # noqa: E402
    AgentsConfig,
    AgentsDefaults,
    AgentSettings,
    UnknownAgentError,
    load_agents_config,
)
from agents.supervisor import (  # noqa: E402
    AGENT_RUNTIME_FAILURES,
    EnabledAgent,
    Observation,
    Supervisor,
)
from plugin_sdk import Agent, DiscoveredPlugin, PluginManifest  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


class _NullAgent(Agent):
    """Minimal Agent — collects events; emits whatever was queued."""

    def __init__(self) -> None:
        super().__init__(_dummy_manifest("test-agent"))
        self.observed: list[dict[str, Any]] = []
        self.queued_proposals: list[dict[str, Any]] = []
        self.observe_delay: float = 0.0
        self.propose_delay: float = 0.0
        self.observe_raises: Exception | None = None
        self.propose_raises: Exception | None = None

    async def observe(self, event: dict[str, Any]) -> None:
        if self.observe_delay:
            await asyncio.sleep(self.observe_delay)
        if self.observe_raises is not None:
            raise self.observe_raises
        self.observed.append(event)

    async def propose(self) -> list[dict[str, Any]]:
        if self.propose_delay:
            await asyncio.sleep(self.propose_delay)
        if self.propose_raises is not None:
            raise self.propose_raises
        emit = list(self.queued_proposals)
        self.queued_proposals.clear()
        return emit


def _dummy_manifest(plugin_id: str) -> PluginManifest:
    return PluginManifest(
        id=plugin_id,
        name=plugin_id,
        kind="agent",
        version="0.0.1",
        sdk_version="*",
        entrypoint="x.y:Z",
    )


@dataclass
class _FakeFeed:
    """Returns the queued observations once, then empties. Tests can
    reload by setting ``next_batch`` again before the next tick.
    """

    next_batch: list[Observation] = field(default_factory=list)

    async def fetch_since(self, *, owner_id: UUID, cursor: datetime | None) -> list[Observation]:
        batch = list(self.next_batch)
        self.next_batch = []
        return batch


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeAgentRepo:
    """Records calls + can be configured to raise on a chosen step."""

    def __init__(self) -> None:
        self.proposals: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.idempotent_keys_seen: set[str] = set()
        self.start_run_raises: Exception | None = None
        self.propose_raises: Exception | None = None
        self.simulate_idempotency_dedup = False

    async def start_run(
        self,
        session: Any,
        *,
        plugin_id: str,
        trigger_kind: str,
        trigger_metadata: dict[str, Any] | None = None,
        owner_id: UUID = uuid4(),
        workspace_id: UUID = uuid4(),
    ) -> UUID:
        if self.start_run_raises is not None:
            raise self.start_run_raises
        run_id = uuid4()
        self.runs.append(
            {
                "id": run_id,
                "plugin_id": plugin_id,
                "trigger_kind": trigger_kind,
                "trigger_metadata": trigger_metadata or {},
            }
        )
        return run_id

    async def mark_run_terminal(
        self,
        session: Any,
        *,
        run_id: UUID,
        status: str,
    ) -> None:
        for run in self.runs:
            if run["id"] == run_id:
                run["status"] = status

    async def propose_action(
        self,
        session: Any,
        *,
        run_id: UUID,
        action_kind: str,
        payload: dict[str, Any],
        rationale: str,
        capability: str,
        idempotency_key: str | None = None,
        owner_id: UUID = uuid4(),
        workspace_id: UUID = uuid4(),
    ) -> UUID | None:
        if self.propose_raises is not None:
            raise self.propose_raises
        if (
            self.simulate_idempotency_dedup
            and idempotency_key is not None
            and idempotency_key in self.idempotent_keys_seen
        ):
            return None
        if idempotency_key is not None:
            self.idempotent_keys_seen.add(idempotency_key)
        proposal_id = uuid4()
        self.proposals.append(
            {
                "id": proposal_id,
                "run_id": run_id,
                "action_kind": action_kind,
                "payload": payload,
                "rationale": rationale,
                "capability": capability,
                "idempotency_key": idempotency_key,
            }
        )
        return proposal_id

    # The Protocol declares a few more methods we don't exercise here.
    async def decide_action(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def execute_action(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def record_event(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def record_artifact(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def fetch_recent_proposals(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def _session_factory():
    @asynccontextmanager
    async def factory():
        yield _FakeSession()

    return factory


def _settings(
    plugin_id: str = "test-agent",
    *,
    tick=60.0,
    timeout=0.5,
    lookback=3600.0,
) -> AgentSettings:
    return AgentSettings(
        plugin_id=plugin_id,
        tick_interval_seconds=tick,
        timeout_seconds=timeout,
        restart_lookback_seconds=lookback,
    )


def _enabled(
    plugin_id: str = "test-agent",
    *,
    agent: _NullAgent | None = None,
    feed: _FakeFeed | None = None,
    settings: AgentSettings | None = None,
) -> EnabledAgent:
    return EnabledAgent(
        plugin_id=plugin_id,
        agent=agent or _NullAgent(),
        observation_feed=feed or _FakeFeed(),
        settings=settings or _settings(plugin_id),
    )


def _counter_value(plugin_id: str, phase: str) -> float:
    """Read the current value of ``AGENT_RUNTIME_FAILURES{plugin_id, phase}``."""
    return AGENT_RUNTIME_FAILURES.labels(plugin_id=plugin_id, phase=phase)._value.get()


# ──────────────────────────────────────────────────────────────────────
# Config — load + validate
# ──────────────────────────────────────────────────────────────────────


def test_load_agents_config_empty_block(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("agents:\n  enabled: []\n")
    cfg = load_agents_config(config_file, discovered=[])
    assert cfg.enabled == []
    assert cfg.resolve() == []


def test_load_agents_config_missing_block_is_empty(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("analysis:\n  daily_briefing:\n    enabled: false\n")
    cfg = load_agents_config(config_file, discovered=[])
    assert cfg.enabled == []


def test_load_agents_config_unknown_agent_id_fails_loud(tmp_path: Path):
    """Phase 7-C invariant: enabling a typo'd plugin id must crash
    startup — silent skip would create phantom safety.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text("agents:\n  enabled: [hdh.agents.does_not_exist]\n")
    with pytest.raises(UnknownAgentError) as exc_info:
        load_agents_config(config_file, discovered=[])
    assert exc_info.value.unknown_id == "hdh.agents.does_not_exist"


def test_load_agents_config_known_agent_id_passes(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("agents:\n  enabled: [hdh.agents.real_one]\n")
    discovered = [
        DiscoveredPlugin(
            plugin_id="hdh.agents.real_one",
            kind="agent",
            plugin_dir=tmp_path,
            manifest=_dummy_manifest("hdh.agents.real_one"),
        )
    ]
    cfg = load_agents_config(config_file, discovered=discovered)
    assert cfg.enabled == ["hdh.agents.real_one"]


def test_resolve_merges_defaults_with_overrides():
    cfg = AgentsConfig(
        enabled=["a", "b"],
        defaults=AgentsDefaults(tick_interval_seconds=60.0, timeout_seconds=5.0),
        overrides={"b": {"tick_interval_seconds": 10.0}},
    )
    resolved = cfg.resolve()
    assert resolved[0].tick_interval_seconds == 60.0
    assert resolved[1].tick_interval_seconds == 10.0
    assert resolved[1].timeout_seconds == 5.0


# ──────────────────────────────────────────────────────────────────────
# Supervisor — empty allowlist starts and idles
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_supervisor_with_no_enabled_agents_starts_and_idles():
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=_FakeAgentRepo(),
        enabled=[],
    )
    await sup.start()
    assert sup._tasks == []
    await sup.stop()


# ──────────────────────────────────────────────────────────────────────
# Supervisor — happy-path tick
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_tick_advances_cursor_and_persists_proposals():
    now = datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
    obs = Observation(
        subject_id="finding-1",
        occurred_at=now,
        payload={"finding_id": "finding-1", "severity": "watch"},
    )
    agent = _NullAgent()
    agent.queued_proposals = [
        {
            "action_kind": "notify",
            "payload": {"text": "elevated HRV"},
            "rationale": "hrv anomaly severity=watch",
            "capability": "propose:notify",
            "subject_id": "finding-1",
        }
    ]
    feed = _FakeFeed(next_batch=[obs])
    repo = _FakeAgentRepo()
    ref = _enabled(agent=agent, feed=feed)
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    await sup.tick_once(ref)

    assert ref.cursor == now, "cursor should advance to observation timestamp"
    assert len(repo.proposals) == 1
    assert repo.proposals[0]["action_kind"] == "notify"
    # ── Idempotency key shape: plugin_id:action_kind:subject_id
    assert repo.proposals[0]["idempotency_key"] == "test-agent:notify:finding-1"


# ──────────────────────────────────────────────────────────────────────
# Supervisor — timeout isolation (observe + propose)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_timeout_is_isolated_and_bumps_counter():
    """A slow observe in one agent must not affect other agents.
    Drives one agent's tick directly to confirm timeout isolation +
    counter increment.
    """
    before = _counter_value("slow-observe-agent", "observe")
    obs = Observation(
        subject_id="finding-1",
        occurred_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    agent = _NullAgent()
    agent.observe_delay = 0.5  # exceeds 0.1s timeout below
    feed = _FakeFeed(next_batch=[obs])
    ref = _enabled(
        "slow-observe-agent",
        agent=agent,
        feed=feed,
        settings=_settings("slow-observe-agent", timeout=0.05),
    )
    repo = _FakeAgentRepo()
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    await sup.tick_once(ref)

    # Cursor must NOT advance (observe phase failed).
    assert ref.cursor is None
    # No proposal was persisted.
    assert repo.proposals == []
    # The named counter incremented.
    after = _counter_value("slow-observe-agent", "observe")
    assert after == before + 1


@pytest.mark.asyncio
async def test_propose_timeout_is_isolated_and_bumps_counter():
    before = _counter_value("slow-propose-agent", "propose")
    obs = Observation(
        subject_id="finding-1",
        occurred_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    agent = _NullAgent()
    agent.propose_delay = 0.5
    feed = _FakeFeed(next_batch=[obs])
    ref = _enabled(
        "slow-propose-agent",
        agent=agent,
        feed=feed,
        settings=_settings("slow-propose-agent", timeout=0.05),
    )
    repo = _FakeAgentRepo()
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    await sup.tick_once(ref)

    # Cursor must NOT advance.
    assert ref.cursor is None
    assert repo.proposals == []
    after = _counter_value("slow-propose-agent", "propose")
    assert after == before + 1


# ──────────────────────────────────────────────────────────────────────
# Supervisor — persist failure keeps cursor (the load-bearing invariant)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_failure_does_not_advance_cursor():
    """The user's correction: cursor must only advance after
    persistence commits. A failed persist must leave the cursor
    untouched so the next tick re-fetches the same observations and
    idempotency dedups proposals.
    """
    before = _counter_value("persist-fail-agent", "persist_proposal")
    obs = Observation(
        subject_id="finding-1",
        occurred_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    agent = _NullAgent()
    agent.queued_proposals = [
        {
            "action_kind": "notify",
            "payload": {"text": "hi"},
            "rationale": "x",
            "capability": "propose:notify",
            "subject_id": "finding-1",
        }
    ]
    feed = _FakeFeed(next_batch=[obs])
    repo = _FakeAgentRepo()
    repo.start_run_raises = RuntimeError("db went away")
    ref = _enabled("persist-fail-agent", agent=agent, feed=feed)
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    initial_cursor = ref.cursor  # None
    await sup.tick_once(ref)

    # The critical invariant — cursor unchanged.
    assert ref.cursor == initial_cursor
    assert repo.proposals == []
    after = _counter_value("persist-fail-agent", "persist_proposal")
    assert after == before + 1


# ──────────────────────────────────────────────────────────────────────
# Idempotency — duplicate finding produces no duplicate proposal
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_finding_does_not_create_duplicate_proposal():
    """Re-fetching the same finding (cursor reset on restart) must NOT
    produce a duplicate proposal — the database's idempotency key
    dedups, and the repo fake mirrors that behavior.
    """
    now = datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
    obs = Observation(
        subject_id="finding-1",
        occurred_at=now,
        payload={"x": 1},
    )

    def make_agent():
        agent = _NullAgent()
        agent.queued_proposals = [
            {
                "action_kind": "notify",
                "payload": {"text": "hi"},
                "rationale": "x",
                "capability": "propose:notify",
                "subject_id": "finding-1",
            }
        ]
        return agent

    repo = _FakeAgentRepo()
    repo.simulate_idempotency_dedup = True

    # Tick 1 — first time we see finding-1, proposal lands.
    feed1 = _FakeFeed(next_batch=[obs])
    ref1 = _enabled(agent=make_agent(), feed=feed1)
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref1],
    )
    await sup.tick_once(ref1)
    assert len(repo.proposals) == 1

    # Tick 2 — same finding, simulated restart (cursor None again).
    feed2 = _FakeFeed(next_batch=[obs])
    ref2 = _enabled(agent=make_agent(), feed=feed2)
    await sup.tick_once(ref2)

    # Repo's idempotency dedup short-circuited; no second proposal.
    assert len(repo.proposals) == 1


# ──────────────────────────────────────────────────────────────────────
# Idempotency — key includes action_kind (the user's correction)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_key_includes_action_kind():
    """The user's correction over my v0 design: idempotency_key shape
    is ``plugin_id:action_kind:subject_id``, NOT
    ``plugin_id:subject_id``. This lets one finding produce one
    proposal per action_kind (one notify, one create_briefing, etc.)
    rather than capping at exactly one proposal per finding.
    """
    obs = Observation(
        subject_id="finding-1",
        occurred_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    agent = _NullAgent()
    agent.queued_proposals = [
        {
            "action_kind": "notify",
            "payload": {},
            "rationale": "x",
            "capability": "propose:notify",
            "subject_id": "finding-1",
        },
        {
            "action_kind": "create_briefing",
            "payload": {},
            "rationale": "y",
            "capability": "propose:create_briefing",
            "subject_id": "finding-1",
        },
    ]
    feed = _FakeFeed(next_batch=[obs])
    repo = _FakeAgentRepo()
    ref = _enabled(agent=agent, feed=feed)
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    await sup.tick_once(ref)

    keys = sorted(p["idempotency_key"] for p in repo.proposals)
    assert keys == [
        "test-agent:create_briefing:finding-1",
        "test-agent:notify:finding-1",
    ]


@pytest.mark.asyncio
async def test_idempotency_key_is_none_when_subject_id_missing():
    """Without ``subject_id``, the supervisor emits no idempotency key —
    matching the AgentRepository contract: a None key always lands.
    """
    obs = Observation(
        subject_id="finding-1",
        occurred_at=datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    agent = _NullAgent()
    agent.queued_proposals = [
        {
            "action_kind": "create_briefing",
            "payload": {},
            "rationale": "manual",
            "capability": "propose:create_briefing",
            # no subject_id
        }
    ]
    feed = _FakeFeed(next_batch=[obs])
    repo = _FakeAgentRepo()
    ref = _enabled(agent=agent, feed=feed)
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=repo,
        enabled=[ref],
    )

    await sup.tick_once(ref)
    assert repo.proposals[0]["idempotency_key"] is None


# ──────────────────────────────────────────────────────────────────────
# Restart-lookback cursor seeding
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_primes_cursor_with_restart_lookback():
    """First boot: cursor is None. start() seeds it to now() - lookback
    so the very first tick doesn't pull every observation since the
    beginning of time.
    """
    fixed_now = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)
    ref = _enabled(
        agent=_NullAgent(),
        feed=_FakeFeed(),
        settings=_settings(timeout=0.5, lookback=3600.0),
    )
    sup = Supervisor(
        session_factory=_session_factory(),
        agents_repo=_FakeAgentRepo(),
        enabled=[ref],
        clock=lambda: fixed_now,
    )
    await sup.start()
    assert ref.cursor == fixed_now - timedelta(seconds=3600.0)
    await sup.stop()
