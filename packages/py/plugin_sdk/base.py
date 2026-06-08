# SPDX-License-Identifier: Apache-2.0
"""Abstract base classes for the three plugin kinds.

Phase 6 ships THREE kinds (parent ISA originally listed four including
``transform`` — that was collapsed into source/narrator surfaces during
the audit). Each base class declares an async lifecycle that the
loader calls. Concrete plugins subclass and implement.

Why ABCs over Protocols: subclass-checking gives the registry a
clear "is this entrypoint a Source?" answer at load time. Protocols
would push that check to runtime + first call.

Lifecycle methods all start with ``async def`` because the runtime
they slot into (FastAPI route handlers, APScheduler async jobs, the
forthcoming agent runtime) is async-first. Returning a coroutine that
raises ``NotImplementedError`` is fine for kinds that don't need a
particular hook (e.g., a stateless Narrator does not need ``shutdown``).

Kinds:

  * :class:`Source` — produces health measurements. Has setup +
    ``ingest`` + shutdown.
  * :class:`Narrator` — turns statistical findings into prose.
    Stateless; one ``render`` call per briefing.
  * :class:`Agent` — autonomous decision-maker. Stateful; subscribes
    to the data plane via ``observe``, emits typed
    :class:`contracts.agents.ActionProposal` objects via ``propose``.
    Phase 7 wires the runtime that actually invokes these; Phase 6
    just ships the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable
from typing import Any

from .manifest import PluginManifest


class Plugin(ABC):
    """Common base — every plugin carries its manifest + a logger.

    Concrete plugins typically subclass :class:`Source`, :class:`Narrator`,
    or :class:`Agent` rather than this — but the loader uses the
    common base to inject the manifest after instantiation so plugins
    don't have to thread it through their own ``__init__``.
    """

    manifest: PluginManifest

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest


class Source(Plugin):
    """Produces health measurements from an upstream system.

    Lifecycle:

      1. ``setup(config)``   — once after instantiation. Open
         connections, load secrets, etc.
      2. ``ingest(payload)`` — invoked per incoming batch (push) or
         per scheduled tick (poll). Returns the count of accepted +
         rejected samples for observability.
      3. ``shutdown()``      — once on graceful exit.

    Sources do NOT write to TimescaleDB directly. They yield
    normalized payloads to the surrounding ingestion runtime, which
    routes through the storage zone (``packages/py/storage/``).
    Phase 6 ships the Apple Health source as the first first-party
    plugin; it wraps the existing :mod:`apps.api.server.api.ingest`
    handler so the legacy POST /api/apple/batch surface keeps working
    unchanged.
    """

    async def setup(self, config: dict[str, Any]) -> None:
        """Optional initialization hook. Default is a no-op."""

    @abstractmethod
    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        """Accept one batch and return ``{"accepted": N, "rejected": N}``."""

    async def shutdown(self) -> None:
        """Optional cleanup hook. Default is a no-op."""


class Narrator(Plugin):
    """Turns structured statistical findings into prose for the user.

    Stateless by contract — the same input must produce a stable
    output (modulo LLM nondeterminism, which is the narrator's
    responsibility to manage via temperature, seed, prompt-hash logging,
    etc.). The runtime calls ``render`` once per briefing.

    The return type is :class:`AsyncIterable` of token chunks so the
    dashboard can stream narration via SSE without buffering the full
    response. Pre-existing in-tree narrators that return a complete
    string are wrapped by the runtime into a single-chunk async
    iterable; new plugins should stream natively.
    """

    @abstractmethod
    def render(
        self, findings: list[dict[str, Any]], *, context: dict[str, Any] | None = None
    ) -> AsyncIterable[str]:
        """Yield narrative chunks for the given findings."""


class Agent(Plugin):
    """Autonomous decision-maker. Subscribes to the data plane and
    proposes typed actions.

    The Phase 6 contract is intentionally minimal — Phase 7 builds the
    runtime that actually invokes ``observe`` + ``propose`` and routes
    proposals through the AgentRun → ActionProposal → ActionDecision →
    ActionExecution ledger (already typed in
    ``packages/py/contracts/agents.py``).

    The base lives in Phase 6 so plugin authors can start writing
    Agents now and the registry can list them; the runtime that
    actually runs them lands in Phase 7-C.

    Lifecycle (Phase 7-pre-min):

      1. ``start()``        — once before the supervisor begins driving
         the agent. Open external connections, prime caches.
      2. ``observe(event)`` — per data-plane event (new measurement,
         finding, user action). Pure side-effect.
      3. ``propose()``      — returns zero or more
         ``ActionProposal``-shaped dicts. The runtime materializes each
         into :class:`contracts.agents.ActionProposal`; malformed
         dicts surface as validation errors, not silent drops.
      4. ``health()``       — runtime polls on a schedule to report
         degraded state.
      5. ``stop()``         — once on graceful shutdown. MUST be
         idempotent — the runtime calls it on clean exit AND
         exception paths.

    Sources have setup/ingest/shutdown; Narrators are stateless. Agents
    are persistent stateful processes — hence the richer lifecycle.
    """

    async def start(self) -> None:
        """Optional lifecycle hook: called once before the supervisor
        begins driving the agent. Default no-op.

        Implementations open external connections, prime caches, or
        register callbacks here. The supervisor catches exceptions and
        re-raises them as :class:`AgentLifecycleError`
        (``plugin_sdk.runtime``); a raise here prevents the agent from
        being scheduled.
        """

    async def stop(self) -> None:
        """Optional lifecycle hook: called once during graceful
        shutdown. Default no-op.

        Implementations close connections, flush state, unregister
        callbacks here. MUST be idempotent — the supervisor calls
        ``stop()`` on both clean exit AND exception paths so any
        cleanup that has already happened must short-circuit.
        """

    async def health(self) -> dict[str, Any]:
        """Report runtime health state. Default returns
        ``{"status": "ok"}``.

        Implementations override to surface degraded modes — e.g.
        ``{"status": "degraded", "reason": "queue full",
        "queue_depth": 42}``. The supervisor polls this on a schedule
        and exposes the result via the dashboard. A raise inside this
        method is caught by the supervisor and re-raised as
        :class:`AgentHealthError` (``plugin_sdk.runtime``); the
        supervisor records the failure but does not treat a single
        unhealthy probe as cause to stop the agent.
        """
        return {"status": "ok"}

    @abstractmethod
    async def observe(self, event: dict[str, Any]) -> None:
        """Receive one event from the data plane (a new measurement,
        an analysis finding, a user action). Pure side-effect.
        """

    @abstractmethod
    async def propose(self) -> list[dict[str, Any]]:
        """Return zero or more ``ActionProposal``-shaped dicts after
        observing enough events to make a decision.

        The runtime materializes each dict into a typed
        :class:`contracts.agents.ActionProposal` and persists it
        through the ledger; a malformed dict surfaces as a validation
        error, not a silent drop.
        """
