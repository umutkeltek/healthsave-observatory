# SPDX-License-Identifier: Apache-2.0
"""Runtime contracts for the Phase 7-C agent supervisor.

Defines:

  * Typed error hierarchy keyed on the agent lifecycle phase. The
    supervisor catches and labels Prometheus counters by phase so
    operators can alert on `start`-time failures distinctly from
    `propose`-time failures (different remediation paths).
  * :func:`error_boundary` — an async context manager that wraps a
    plugin call and re-raises any generic ``Exception`` as the typed
    :class:`AgentRuntimeError` subclass for the phase. Already-typed
    runtime errors pass through unchanged (idempotent).
  * :func:`with_deadline` — an asyncio wrapper that enforces a wall
    clock timeout per call, raising :class:`AgentTimeoutError` on
    deadline overrun and cancelling the inner coroutine.

The supervisor in :mod:`apps.agents` (Phase 7-C) uses these primitives
around every call to ``Agent.start`` / ``stop`` / ``health`` /
``observe`` / ``propose``. The Phase 5G observability pattern applies:
every silently-handled exception in the runtime layer MUST bump a
named counter — the supervisor wires that up; the SDK ships the
exception types.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import asynccontextmanager

from .errors import PluginError

log = logging.getLogger("plugin_sdk.runtime")


# ──────────────────────────────────────────────────────────────────────
# Typed error hierarchy
# ──────────────────────────────────────────────────────────────────────


class AgentRuntimeError(PluginError):
    """Base for runtime-side agent failures.

    The supervisor catches the base; specific subclasses let operators
    differentiate observe-time failures from propose-time failures from
    lifecycle failures via the ``phase`` attribute and the
    ``AGENT_RUNTIME_FAILURES{plugin_id, phase}`` counter the supervisor
    will bump (Phase 5G observability pattern).
    """

    def __init__(self, *, plugin_id: str, phase: str, message: str) -> None:
        super().__init__(f"agent {plugin_id!r} failed in {phase!r} phase: {message}")
        self.plugin_id = plugin_id
        self.phase = phase
        self.message = message


class AgentLifecycleError(AgentRuntimeError):
    """``start`` or ``stop`` raised. Agent likely not scheduled or not
    cleanly shut down — supervisor will retry start with backoff;
    stop failures are logged but never block exit.
    """


class AgentHealthError(AgentRuntimeError):
    """``health`` raised. A single failure does NOT cause the supervisor
    to stop the agent — the supervisor logs + counters and treats the
    next successful probe as recovery. Repeated failures (alert via
    counter rate) prompt operator intervention.
    """


class AgentObserveError(AgentRuntimeError):
    """``observe(event)`` raised. The event is lost from this agent's
    perspective (supervisor decides whether to dead-letter); other
    agents observing the same event are unaffected.
    """


class AgentProposeError(AgentRuntimeError):
    """``propose()`` raised. No proposals emitted for this tick.
    Supervisor will retry on the next tick; persistent propose failures
    indicate logic-level breakage and require operator attention.
    """


class AgentTimeoutError(AgentRuntimeError):
    """A plugin call exceeded its deadline. The supervisor cancelled
    the inner coroutine; the original :class:`asyncio.TimeoutError` is
    chained via ``__cause__``.

    Distinct from the phase-specific errors so operators can alert on
    *resource exhaustion* (timeout) separately from *logic exceptions*
    (other AgentRuntimeError subclasses) under the same
    ``{plugin_id, phase}`` label structure.
    """


_PHASE_TO_ERROR: dict[str, type[AgentRuntimeError]] = {
    "start": AgentLifecycleError,
    "stop": AgentLifecycleError,
    "health": AgentHealthError,
    "observe": AgentObserveError,
    "propose": AgentProposeError,
}


# ──────────────────────────────────────────────────────────────────────
# error_boundary — wrap plugin calls with typed re-raise
# ──────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def error_boundary(plugin_id: str, phase: str):
    """Wrap a plugin call with typed-exception re-raise.

    Usage::

        async with error_boundary("anomaly-watcher", phase="observe"):
            await agent.observe(event)

    Any generic ``Exception`` raised inside the block surfaces as the
    typed :class:`AgentRuntimeError` subclass for that phase. The
    original exception is chained via ``__cause__`` for grep-able
    operator output. Already-typed :class:`AgentRuntimeError` exceptions
    (including :class:`AgentTimeoutError`) pass through unchanged so
    nested boundaries don't double-wrap.

    Unknown phases get the :class:`AgentRuntimeError` base class so the
    supervisor still gets a typed error even if it labels with a phase
    string the SDK doesn't recognize.

    ``asyncio.CancelledError`` is NOT caught — cancellation must
    propagate to let :func:`with_deadline` cancel the inner coroutine
    and let the supervisor's own cancellation pathways work. Catching
    CancelledError here would mask shutdown signals.
    """
    typed = _PHASE_TO_ERROR.get(phase, AgentRuntimeError)
    try:
        yield
    except AgentRuntimeError:
        # Already typed — don't re-wrap. Idempotency under nesting.
        raise
    except asyncio.CancelledError:
        # Never swallow cancellation; let it propagate.
        raise
    except Exception as exc:
        raise typed(
            plugin_id=plugin_id,
            phase=phase,
            message=f"{type(exc).__name__}: {exc}",
        ) from exc


# ──────────────────────────────────────────────────────────────────────
# with_deadline — wrap plugin calls with a wall-clock timeout
# ──────────────────────────────────────────────────────────────────────


async def with_deadline[T](
    coro: Awaitable[T],
    *,
    seconds: float,
    plugin_id: str,
    phase: str,
) -> T:
    """Run a coroutine with a hard deadline.

    Returns the coroutine's value if it completes inside the deadline.
    Raises :class:`AgentTimeoutError` (with the original
    :class:`asyncio.TimeoutError` chained via ``__cause__``) if the
    deadline elapses; the inner coroutine receives
    :class:`asyncio.CancelledError` before this function returns
    control to the caller.

    Usage::

        result = await with_deadline(
            agent.observe(event),
            seconds=5.0,
            plugin_id="anomaly-watcher",
            phase="observe",
        )

    Composes with :func:`error_boundary` — the typical supervisor
    pattern is ``error_boundary`` outside, ``with_deadline`` inside::

        async with error_boundary("anomaly-watcher", phase="observe"):
            await with_deadline(
                agent.observe(event),
                seconds=5.0,
                plugin_id="anomaly-watcher",
                phase="observe",
            )

    error_boundary lets AgentTimeoutError pass through (it's already an
    AgentRuntimeError subclass) so the timeout type is preserved.
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except TimeoutError as exc:
        raise AgentTimeoutError(
            plugin_id=plugin_id,
            phase=phase,
            message=f"deadline exceeded after {seconds:.3f}s",
        ) from exc
