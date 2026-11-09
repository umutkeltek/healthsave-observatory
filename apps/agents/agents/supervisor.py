"""Agent supervisor — Phase 7-C.

Per-agent tick loop with three-phase error_boundary
(``observe`` / ``propose`` / ``persist_proposal``), cursor-after-commit
semantics, and a typed-Prometheus counter on every silently-handled
failure (:data:`AGENT_RUNTIME_FAILURES`).

The supervisor is feed-agnostic: it consumes an :class:`ObservationFeed`
Protocol — Phase 7-D supplies the concrete ``AnalysisFindingsAnomalyFeed``.
Keeping the feed out of 7-C is deliberate — the user's design review
flagged that ``briefings.fetch_anomalies(...)`` leaks the anomaly axis
into the supervisor commit and breaks the 7-C/7-D boundary.

Cursor discipline: in-memory per-agent watermark; on restart, fall back
to ``now() - restart_lookback_seconds``. Re-processing is safe because
proposal persistence uses ``idempotency_key = f"{plugin_id}:{action_kind}:{subject_id}"``
and the database has a partial unique index that dedups.

Boundary contract (enforced by :mod:`tests.contract.test_apps_agents_boundary`):

  * ``apps/agents/`` may NOT import from ``server.api.*`` /
    ``server.ingestion.*`` etc. Only ``server.db.session`` (engine
    bootstrap) is allowed.
  * ``plugins/agents/`` may NOT import any ``server.*`` symbol.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, get_args, runtime_checkable
from uuid import UUID

from plugin_sdk import (
    Agent,
    AgentRuntimeError,
    error_boundary,
    load_plugin,
    with_deadline,
)
from prometheus_client import Counter
from storage.ports import AgentRepository
from storage.timescale.agents import DEFAULT_OWNER_ID, ActionKind, default_repository

from .config import AgentSettings

log = logging.getLogger("agents.supervisor")


# ──────────────────────────────────────────────────────────────────────
# Observability — Phase 5G named counter for every swallowed failure
# ──────────────────────────────────────────────────────────────────────

AGENT_RUNTIME_FAILURES = Counter(
    "agent_runtime_failures_total",
    "Agent plugin call failures, labeled by plugin id and lifecycle phase.",
    ["plugin_id", "phase"],
)

PROPOSAL_INVALID_PHASE = "proposal_invalid"
"""``AGENT_RUNTIME_FAILURES`` phase for a proposal the supervisor dropped
because the store could never accept it (see :func:`proposal_problem`)."""


# ──────────────────────────────────────────────────────────────────────
# Proposal validation — what action_proposals can never accept
# ──────────────────────────────────────────────────────────────────────

_KNOWN_ACTION_KINDS: frozenset[str] = frozenset(get_args(ActionKind))


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, Mapping):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_nul(item) for item in value)
    return False


def proposal_problem(proposal: Any) -> str | None:
    """Why ``action_proposals`` would reject ``proposal`` on every retry,
    or ``None`` when it is storable.

    Mirrors the table (migration 006): the ``action_kind`` CHECK, NOT NULL
    ``rationale`` / ``capability`` text, a JSON-object ``payload`` (every
    reader types it as a dict), and nothing PostgreSQL cannot store (NaN or
    Infinity in jsonb, NUL in text or jsonb). The supervisor drops such a
    proposal instead of letting it fail the tick: a deterministic rejection
    would otherwise hold the cursor, re-feed the same observations, and
    produce the same proposal forever.
    """
    if not isinstance(proposal, Mapping):
        return f"proposal is a {type(proposal).__name__}, not a mapping"
    action_kind = proposal.get("action_kind")
    if not isinstance(action_kind, str) or action_kind not in _KNOWN_ACTION_KINDS:
        return f"unknown action_kind {action_kind!r}"
    for column in ("rationale", "capability"):
        value = proposal.get(column, "")
        if not isinstance(value, str):
            return f"{column} is a {type(value).__name__}, not text"
        if "\x00" in value:
            return f"{column} contains a NUL character"
    subject_id = proposal.get("subject_id")
    if subject_id is not None and "\x00" in str(subject_id):
        return "subject_id contains a NUL character"
    payload = proposal.get("payload", {})
    if not isinstance(payload, Mapping):
        return f"payload is a {type(payload).__name__}, not a JSON object"
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        return f"payload is not storable JSON ({exc})"
    if _contains_nul(payload):
        return "payload contains a NUL character"
    return None


# ──────────────────────────────────────────────────────────────────────
# Observation seam — Phase 7-D supplies the concrete feed
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One unit consumed by :meth:`plugin_sdk.Agent.observe`.

    ``subject_id`` is the stable identity used by the supervisor to
    derive proposal idempotency keys (``plugin_id:action_kind:subject_id``).
    For an anomaly-watcher, ``subject_id`` is the ``analysis_findings.id``;
    for future feeds, anything stable across re-fetches.

    ``occurred_at`` is the cursor advance target — the supervisor takes
    the max of observed timestamps after a successful persistence commit.
    """

    subject_id: str
    occurred_at: datetime
    payload: dict[str, Any]


@runtime_checkable
class ObservationFeed(Protocol):
    """Source of observations for an :class:`Agent`. Phase 7-D ships
    ``AnalysisFindingsAnomalyFeed`` as the first concrete impl.

    Discipline:

      * Methods are async.
      * The feed is the only place that knows where observations come
        from — keep storage queries inside the feed, not the supervisor.
      * Return order MUST be ascending by ``occurred_at`` so the
        supervisor's ``max(occurred_at)`` cursor advance is correct.
      * The next call excludes everything at or before that cursor, so a
        capped batch MUST be the OLDEST observations after the cursor
        (newest-first would skip the rest of a backlog) and MUST NOT end
        in the middle of a group sharing one ``occurred_at`` (the rest of
        the group would be skipped).
    """

    async def fetch_since(
        self,
        *,
        owner_id: UUID,
        cursor: datetime | None,
    ) -> list[Observation]:
        """Return observations strictly newer than ``cursor`` (or all
        observations when ``cursor`` is ``None`` — initial-load shape).
        """
        ...


# ──────────────────────────────────────────────────────────────────────
# EnabledAgent — supervisor's per-agent state
# ──────────────────────────────────────────────────────────────────────


@dataclass
class EnabledAgent:
    """One scheduled agent — the plugin instance, its observation feed,
    its resolved settings, and its in-memory cursor.

    The supervisor mutates ``cursor`` after each successful
    ``persist_proposal`` phase. The cursor is intentionally NOT
    persisted — restart-replay with idempotency dedup is the durable
    truth for v0. Phase 9+ may add a cursor table if observation
    queries become expensive.
    """

    plugin_id: str
    agent: Agent
    observation_feed: ObservationFeed
    settings: AgentSettings
    cursor: datetime | None = None
    owner_id: UUID = field(default=DEFAULT_OWNER_ID)


# ──────────────────────────────────────────────────────────────────────
# Supervisor
# ──────────────────────────────────────────────────────────────────────


class Supervisor:
    """Always-on driver for a set of :class:`EnabledAgent` instances.

    Lifecycle:

      1. :meth:`start` — call each agent's :meth:`plugin_sdk.Agent.start`
         (wrapped in error_boundary("start")) and spawn one asyncio task
         per agent that runs :meth:`_run_agent` until cancelled.
      2. :meth:`stop` — cancel every agent task, then call each agent's
         :meth:`plugin_sdk.Agent.stop` (wrapped in error_boundary("stop")).
         Idempotent — safe to call multiple times.

    Discipline:

      * One asyncio task per agent — observe/propose timeouts in one
        agent do NOT freeze ticks for other agents.
      * The session factory is injected — production passes
        ``server.db.session.async_session``, tests pass a fake.
      * Cursor advance is downstream of ``session.commit()``. A persist
        failure leaves the cursor unchanged so the next tick re-fetches
        the same observations and idempotency dedups proposals.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        agents_repo: AgentRepository | None = None,
        enabled: list[EnabledAgent],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._agents_repo: AgentRepository = agents_repo or default_repository
        self._enabled = enabled
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        """Prime cursors, call each agent's ``start()``, spawn tick tasks."""
        for ref in self._enabled:
            if ref.cursor is None and ref.settings.restart_lookback_seconds > 0:
                ref.cursor = self._clock() - timedelta(
                    seconds=ref.settings.restart_lookback_seconds
                )
            try:
                async with error_boundary(ref.plugin_id, phase="start"):
                    await with_deadline(
                        ref.agent.start(),
                        seconds=ref.settings.timeout_seconds,
                        plugin_id=ref.plugin_id,
                        phase="start",
                    )
            except AgentRuntimeError as exc:
                # Lifecycle failure: do not schedule this agent, but do
                # not crash the supervisor — other agents may still be
                # healthy.
                AGENT_RUNTIME_FAILURES.labels(plugin_id=exc.plugin_id, phase=exc.phase).inc()
                log.warning("agent %s start failed: %s", ref.plugin_id, exc)
                continue
            self._tasks.append(asyncio.create_task(self._run_agent(ref)))

    async def stop(self) -> None:
        """Signal stop, cancel tick tasks, call each agent's ``stop()``."""
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for ref in self._enabled:
            try:
                async with error_boundary(ref.plugin_id, phase="stop"):
                    await with_deadline(
                        ref.agent.stop(),
                        seconds=ref.settings.timeout_seconds,
                        plugin_id=ref.plugin_id,
                        phase="stop",
                    )
            except AgentRuntimeError as exc:
                AGENT_RUNTIME_FAILURES.labels(plugin_id=exc.plugin_id, phase=exc.phase).inc()
                log.warning("agent %s stop failed: %s", ref.plugin_id, exc)

    # -- per-agent loop ------------------------------------------------

    async def _run_agent(self, ref: EnabledAgent) -> None:
        """Tick ``ref`` forever — one tick per ``tick_interval_seconds``.

        Cancellation lands at the ``asyncio.sleep`` boundary; the inner
        ``_tick`` call completes cleanly because plugin calls are wrapped
        in ``with_deadline`` (bounded), error_boundary (typed), and the
        whole tick is wrapped in ``try/except`` so one tick's failure
        never breaks the loop.
        """
        while not self._stopping.is_set():
            try:
                await self.tick_once(ref)
            except Exception as exc:
                # Defensive — _tick handles AgentRuntimeError and bumps
                # counters; only an unexpected supervisor-level bug
                # reaches here. Log and continue (the alternative,
                # crashing the agent's loop, would silently disable it).
                log.exception("supervisor tick crashed for %s: %s", ref.plugin_id, exc)
            try:
                await asyncio.sleep(ref.settings.tick_interval_seconds)
            except asyncio.CancelledError:
                return

    async def tick_once(self, ref: EnabledAgent) -> None:
        """Run exactly one tick for ``ref``. Public for testability —
        the tests drive this directly rather than waiting for the
        sleep-based loop.

        Three phases — each wrapped in its own ``error_boundary``:

          1. ``observe``         — fetch new observations + feed each one
                                   to ``agent.observe(payload)``.
          2. ``propose``         — call ``agent.propose()`` for a list of
                                   proposal dicts.
          3. ``persist_proposal`` — open a run row, write each proposal
                                   with derived idempotency key, mark
                                   the run terminal, ``commit()``.

        Cursor advances ONLY after ``commit()`` returns. A failure in
        any phase short-circuits the remaining phases for this tick and
        bumps :data:`AGENT_RUNTIME_FAILURES`.

        Between propose and persist, a proposal the store would reject on
        every retry (:func:`proposal_problem`) is dropped and counted under
        ``phase="proposal_invalid"``; the rest persist and the cursor
        advances. Holding the cursor for it would replay the same proposal
        forever. A store error while persisting still fails the phase and
        holds the cursor.
        """
        observations: list[Observation] = []
        proposals: list[dict[str, Any]] = []

        # Phase 1: observe
        try:
            async with error_boundary(ref.plugin_id, phase="observe"):
                observations = await with_deadline(
                    ref.observation_feed.fetch_since(owner_id=ref.owner_id, cursor=ref.cursor),
                    seconds=ref.settings.timeout_seconds,
                    plugin_id=ref.plugin_id,
                    phase="observe",
                )
                for obs in observations:
                    await with_deadline(
                        ref.agent.observe(obs.payload),
                        seconds=ref.settings.timeout_seconds,
                        plugin_id=ref.plugin_id,
                        phase="observe",
                    )
        except AgentRuntimeError as exc:
            AGENT_RUNTIME_FAILURES.labels(plugin_id=exc.plugin_id, phase=exc.phase).inc()
            log.warning("agent %s observe failed: %s", ref.plugin_id, exc)
            return

        # Phase 2: propose
        try:
            async with error_boundary(ref.plugin_id, phase="propose"):
                proposals = await with_deadline(
                    ref.agent.propose(),
                    seconds=ref.settings.timeout_seconds,
                    plugin_id=ref.plugin_id,
                    phase="propose",
                )
        except AgentRuntimeError as exc:
            AGENT_RUNTIME_FAILURES.labels(plugin_id=exc.plugin_id, phase=exc.phase).inc()
            log.warning("agent %s propose failed: %s", ref.plugin_id, exc)
            return

        # Drop what the store can never accept. Retrying it cannot help, and
        # a failed persist would hold the cursor and replay it forever.
        proposals = self._storable_proposals(ref, proposals)

        # Phase 3: persist + commit + cursor advance
        try:
            async with error_boundary(ref.plugin_id, phase="persist_proposal"):
                await self._persist(ref, observations, proposals)
        except AgentRuntimeError as exc:
            AGENT_RUNTIME_FAILURES.labels(plugin_id=exc.plugin_id, phase=exc.phase).inc()
            log.warning("agent %s persist_proposal failed: %s", ref.plugin_id, exc)
            return

        # Cursor advance — ONLY after persist commit succeeded.
        if observations:
            ref.cursor = max(obs.occurred_at for obs in observations)

    @staticmethod
    def _storable_proposals(ref: EnabledAgent, proposals: Any) -> list[dict[str, Any]]:
        """Return the proposals :func:`proposal_problem` accepts; log and
        count each one it drops under ``phase="proposal_invalid"``.
        """
        if not isinstance(proposals, list | tuple):
            AGENT_RUNTIME_FAILURES.labels(
                plugin_id=ref.plugin_id, phase=PROPOSAL_INVALID_PHASE
            ).inc()
            log.warning(
                "agent %s propose() returned a %s, not a list; dropped",
                ref.plugin_id,
                type(proposals).__name__,
            )
            return []
        storable: list[dict[str, Any]] = []
        for proposal in proposals:
            problem = proposal_problem(proposal)
            if problem is None:
                storable.append(proposal)
                continue
            AGENT_RUNTIME_FAILURES.labels(
                plugin_id=ref.plugin_id, phase=PROPOSAL_INVALID_PHASE
            ).inc()
            log.warning(
                "agent %s proposal dropped, the store would reject it: %s (subject_id=%r)",
                ref.plugin_id,
                problem,
                proposal.get("subject_id") if isinstance(proposal, Mapping) else None,
            )
        return storable

    async def _persist(
        self,
        ref: EnabledAgent,
        observations: list[Observation],
        proposals: list[dict[str, Any]],
    ) -> None:
        """Open a run row, write each proposal with derived idempotency
        key, mark the run terminal, ``commit()``.

        Called inside ``error_boundary("persist_proposal")`` — any
        exception is the caller's to handle.
        """
        async with self._session_factory() as session:
            run_id = await self._agents_repo.start_run(
                session,
                plugin_id=ref.plugin_id,
                trigger_kind="cron",
                trigger_metadata={"observations": len(observations)},
                owner_id=ref.owner_id,
            )
            for proposal in proposals:
                subject_id = proposal.get("subject_id")
                action_kind = proposal["action_kind"]
                idempotency_key: str | None = (
                    f"{ref.plugin_id}:{action_kind}:{subject_id}"
                    if subject_id is not None
                    else None
                )
                await self._agents_repo.propose_action(
                    session,
                    run_id=run_id,
                    action_kind=action_kind,
                    payload=proposal.get("payload", {}),
                    rationale=proposal.get("rationale", ""),
                    capability=proposal.get("capability", ""),
                    idempotency_key=idempotency_key,
                    owner_id=ref.owner_id,
                )
            await self._agents_repo.mark_run_terminal(session, run_id=run_id, status="completed")
            await session.commit()


# ──────────────────────────────────────────────────────────────────────
# Boot helper — assemble EnabledAgent list from resolved settings
# ──────────────────────────────────────────────────────────────────────


def build_enabled_agents(
    resolved: list[AgentSettings],
    *,
    observation_feed_factory: Callable[[str], ObservationFeed],
    plugins_dir: Any = None,
) -> list[EnabledAgent]:
    """Materialize :class:`EnabledAgent` instances from resolved settings.

    ``observation_feed_factory`` is a ``plugin_id -> ObservationFeed`` —
    in Phase 7-C it is supplied by ``agents.main`` (Phase 7-D will fill
    in a real factory; for now production wiring is deferred and tests
    inject fakes). Plugin instances come from
    :func:`plugin_sdk.load_plugin` — the same loader-time SDK version
    check the apple_batch route uses (Phase 6.1).
    """
    enabled: list[EnabledAgent] = []
    for settings in resolved:
        agent = load_plugin(settings.plugin_id, kind="agent", plugins_dir=plugins_dir)
        if not isinstance(agent, Agent):  # pragma: no cover — loader enforces
            raise TypeError(f"plugin {settings.plugin_id!r} did not load as Agent")
        feed = observation_feed_factory(settings.plugin_id)
        enabled.append(
            EnabledAgent(
                plugin_id=settings.plugin_id,
                agent=agent,
                observation_feed=feed,
                settings=settings,
            )
        )
    return enabled


@asynccontextmanager
async def supervisor_lifespan(
    supervisor: Supervisor,
) -> AsyncIterator[Supervisor]:
    """Context-manager wrapper for tests + main — ensures ``stop()``
    runs on both clean exit and exception paths.
    """
    await supervisor.start()
    try:
        yield supervisor
    finally:
        await supervisor.stop()


# Compatibility re-exports for callers that import from this module.
__all__ = [
    "AGENT_RUNTIME_FAILURES",
    "EnabledAgent",
    "Observation",
    "ObservationFeed",
    "Supervisor",
    "build_enabled_agents",
    "supervisor_lifespan",
]
