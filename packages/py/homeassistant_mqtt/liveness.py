"""Liveness watchdog for the Home Assistant MQTT bridge.

The bridge can go silently dark: the process stays alive and the loop keeps
spinning, but every publish is skipped (broker gone, paho's network thread dead,
DB stalled). Nothing raises, so ``restart: unless-stopped`` never fires — the
container sits "Up" and dark. This is exactly the failure that left the bridge
silent for ~8 days.

The watchdog makes that condition self-healing: the run loop records each cycle
in which a publish *actually went out*, and if none has for ``deadline_seconds``
it raises :class:`BridgeStalled` so the process exits non-zero and Docker
restarts a clean one (fresh paho thread + DB engine).

Kept pure and clock-injected so it is unit-testable with no asyncio, no
sleeping, no broker, and no DB.
"""

from __future__ import annotations


class BridgeStalled(RuntimeError):
    """Raised when the bridge has not published within the liveness deadline."""


class LivenessWatchdog:
    """Tracks time since the last successful publish; flags a sustained stall.

    All times are caller-supplied monotonic seconds (e.g. ``loop.time()``), so
    behaviour is deterministic under test without touching the clock.
    """

    def __init__(self, deadline_seconds: float) -> None:
        self.deadline_seconds = deadline_seconds
        self._last_ok: float | None = None

    def mark_start(self, now: float) -> None:
        """Arm the watchdog at loop start so boot + first-connect get full grace."""

        self._last_ok = now

    def record_publish(self, now: float) -> None:
        """Record a cycle in which at least one publish actually went out."""

        self._last_ok = now

    def seconds_since_publish(self, now: float) -> float:
        if self._last_ok is None:
            return 0.0
        return now - self._last_ok

    def is_stalled(self, now: float) -> bool:
        # Not armed yet -> not stalled (avoids a false positive before mark_start).
        if self._last_ok is None:
            return False
        return (now - self._last_ok) > self.deadline_seconds
