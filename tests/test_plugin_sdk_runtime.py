"""Phase 7-pre-min runtime contract tests.

Covers:

  * Typed error hierarchy — every concrete error subclasses
    AgentRuntimeError which subclasses PluginError.
  * error_boundary — generic exceptions surface as the typed subclass
    keyed on phase; already-typed errors pass through; CancelledError
    is never swallowed.
  * with_deadline — happy path returns the value; over-deadline raises
    AgentTimeoutError with the inner coroutine cancelled.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_sdk import (  # noqa: E402
    AgentHealthError,
    AgentLifecycleError,
    AgentObserveError,
    AgentProposeError,
    AgentRuntimeError,
    AgentTimeoutError,
    PluginError,
    error_boundary,
    with_deadline,
)

# ──────────────────────────────────────────────────────────────────────
# Typed error hierarchy
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cls",
    [
        AgentRuntimeError,
        AgentLifecycleError,
        AgentHealthError,
        AgentObserveError,
        AgentProposeError,
        AgentTimeoutError,
    ],
)
def test_every_runtime_error_subclasses_plugin_error(cls):
    """Existing fail-loud handlers that catch PluginError must continue
    to catch every runtime error type — that's the Phase 7-pre contract
    for backward compatibility with Phase 6 code.
    """
    assert issubclass(cls, PluginError)
    if cls is not AgentRuntimeError:
        assert issubclass(cls, AgentRuntimeError)


def test_runtime_error_carries_plugin_id_phase_and_message():
    exc = AgentObserveError(
        plugin_id="anomaly-watcher",
        phase="observe",
        message="upstream gone",
    )
    assert exc.plugin_id == "anomaly-watcher"
    assert exc.phase == "observe"
    assert exc.message == "upstream gone"
    assert "anomaly-watcher" in str(exc)
    assert "observe" in str(exc)


# ──────────────────────────────────────────────────────────────────────
# error_boundary — typed re-raise keyed on phase
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,expected_type",
    [
        ("start", AgentLifecycleError),
        ("stop", AgentLifecycleError),
        ("health", AgentHealthError),
        ("observe", AgentObserveError),
        ("propose", AgentProposeError),
    ],
)
async def test_error_boundary_re_raises_phase_specific_typed_error(phase, expected_type):
    """A generic Exception inside the boundary surfaces as the typed
    subclass for the phase. This is the load-bearing claim — Phase 7-C
    will alert on AgentObserveError vs AgentProposeError differently.
    """
    with pytest.raises(expected_type) as exc:
        async with error_boundary("anomaly-watcher", phase=phase):
            raise ValueError("upstream gone")
    assert exc.value.plugin_id == "anomaly-watcher"
    assert exc.value.phase == phase
    # Original exception chained for grep-able operator output.
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_error_boundary_unknown_phase_falls_back_to_base_type():
    """A phase string the SDK doesn't recognize (typo, custom label)
    still surfaces as AgentRuntimeError — not as the raw underlying
    exception. Supervisor can label by whatever phase string it uses.
    """
    with pytest.raises(AgentRuntimeError) as exc:
        async with error_boundary("anomaly-watcher", phase="custom-phase"):
            raise ValueError("oops")
    assert type(exc.value) is AgentRuntimeError
    assert exc.value.phase == "custom-phase"


@pytest.mark.asyncio
async def test_error_boundary_passes_already_typed_errors_through_unchanged():
    """Idempotency: nesting error_boundary inside error_boundary must
    not double-wrap. An AgentProposeError raised inside an outer
    `phase=observe` boundary stays an AgentProposeError.
    """
    original = AgentProposeError(
        plugin_id="anomaly-watcher",
        phase="propose",
        message="raised by inner boundary",
    )
    with pytest.raises(AgentProposeError) as exc:
        async with error_boundary("anomaly-watcher", phase="observe"):
            raise original
    # Same instance — not wrapped.
    assert exc.value is original


@pytest.mark.asyncio
async def test_error_boundary_never_swallows_cancelled_error():
    """asyncio.CancelledError MUST propagate so with_deadline and the
    supervisor's shutdown pathways work. Catching it inside the
    boundary would mask cancellation signals.
    """
    with pytest.raises(asyncio.CancelledError):
        async with error_boundary("anomaly-watcher", phase="observe"):
            raise asyncio.CancelledError("supervisor shutdown")


@pytest.mark.asyncio
async def test_error_boundary_is_transparent_on_happy_path():
    """No exception → boundary is a no-op."""
    sentinel = []
    async with error_boundary("anomaly-watcher", phase="observe"):
        sentinel.append("ran")
    assert sentinel == ["ran"]


# ──────────────────────────────────────────────────────────────────────
# with_deadline — timeout wrapper
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_deadline_returns_value_on_happy_path():
    async def quick():
        await asyncio.sleep(0)
        return 42

    result = await with_deadline(quick(), seconds=1.0, plugin_id="anomaly-watcher", phase="observe")
    assert result == 42


@pytest.mark.asyncio
async def test_with_deadline_raises_agent_timeout_error_on_overrun():
    async def slow():
        await asyncio.sleep(1.0)
        return "should not be returned"

    with pytest.raises(AgentTimeoutError) as exc:
        await with_deadline(slow(), seconds=0.05, plugin_id="anomaly-watcher", phase="observe")
    assert exc.value.plugin_id == "anomaly-watcher"
    assert exc.value.phase == "observe"
    assert "0.050s" in str(exc.value)
    # The original asyncio.TimeoutError is chained for diagnostics.
    assert isinstance(exc.value.__cause__, asyncio.TimeoutError)


@pytest.mark.asyncio
async def test_with_deadline_cancels_inner_coroutine_on_overrun():
    """When the deadline fires, the inner coroutine must receive
    CancelledError — it cannot be left running.
    """
    observed: list[str] = []

    async def cancellable():
        try:
            await asyncio.sleep(1.0)
            observed.append("completed")
        except asyncio.CancelledError:
            observed.append("cancelled")
            raise

    with pytest.raises(AgentTimeoutError):
        await with_deadline(
            cancellable(), seconds=0.05, plugin_id="anomaly-watcher", phase="observe"
        )
    # Yield so the cancelled task's except branch runs before assertion.
    await asyncio.sleep(0)
    assert "cancelled" in observed
    assert "completed" not in observed


@pytest.mark.asyncio
async def test_with_deadline_composes_with_error_boundary():
    """The supervisor's canonical pattern: outer error_boundary + inner
    with_deadline. AgentTimeoutError must propagate through
    error_boundary unwrapped (it's already typed).
    """

    async def slow():
        await asyncio.sleep(1.0)
        return None

    with pytest.raises(AgentTimeoutError):
        async with error_boundary("anomaly-watcher", phase="observe"):
            await with_deadline(slow(), seconds=0.05, plugin_id="anomaly-watcher", phase="observe")
