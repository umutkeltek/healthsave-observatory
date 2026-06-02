"""Replay orchestrator (ADR-0001 Decision H).

Re-normalize stored raw source payloads through the *current* normalizer to
(re)produce canonical observations. Idempotent backfill today; value-changing
supersede is deferred (see :mod:`replay.orchestrator`).
"""

from .orchestrator import ReplayReport, replay_apple_raw_payloads

__all__ = ["ReplayReport", "replay_apple_raw_payloads"]
