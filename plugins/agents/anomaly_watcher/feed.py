"""Concrete :class:`agents.supervisor.ObservationFeed` for the
anomaly-watcher plugin.

Reads ``analysis_findings`` through the briefing repository
(:meth:`storage.timescale.briefings.TimescaleBriefingRepository.fetch_anomalies_after`),
filters to operator-attention severities (``watch`` + ``alert``), and
converts each :class:`storage.timescale.briefings.FindingRow` to an
:class:`agents.supervisor.Observation`.

Four contracts this feed enforces:

  1. **Severity allowlist.** The default is ``("watch", "alert")`` —
     ``info`` is intentionally excluded because that's the "noted but
     not actionable" tier from
     :func:`packages.py.analysis.statistical.anomaly._severity_for`.
     Operators can override via the feed constructor when tuning.
  2. **Oldest first, strictly after the cursor.** The supervisor
     advances its cursor to ``max(observation.occurred_at)`` once a tick
     commits, and the next read excludes everything at or before it. So
     each page is the OLDEST findings after the cursor, in ascending
     ``created_at`` order: a backlog larger than ``limit`` drains over
     several ticks instead of losing its oldest rows.
  3. **Whole timestamp groups.** One analysis run writes all of its
     findings in one transaction, so they share one ``created_at``. A
     page never ends in the middle of such a group (the storage read
     extends the page to finish it), so the exclusive cursor can never
     skip the rest of a group, and a group bigger than ``limit`` cannot
     pin the cursor in place.
  4. **Late commits.** ``created_at`` is the writing transaction's START.
     A daily briefing holds its transaction through the LLM call, so its
     findings can commit after later-stamped ones the cursor has passed.
     Each fetch therefore also re-reads :data:`LATE_COMMIT_WINDOW` behind
     the cursor and returns what it has not delivered yet. A finding counts
     as delivered once the supervisor acknowledges the tick that carried it
     (after its commit), so a failed tick loses nothing. A finding that
     commits more than the window late is still missed.

The feed opens its own short-lived session via the injected
``session_factory`` — the supervisor's tick reuses the factory for the
persist phase, but each phase gets its own session. No long-lived
transactions span observe + propose + persist.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from agents.supervisor import Observation
from storage.timescale.briefings import FindingRow
from storage.timescale.briefings import default_repository as default_briefing_repository

log = logging.getLogger("healthsave.plugins.anomaly_watcher.feed")


DEFAULT_SEVERITIES: tuple[str, ...] = ("watch", "alert")

LATE_COMMIT_WINDOW = timedelta(hours=1)
"""How far behind the cursor each fetch looks for findings committed late
(contract 4). Far longer than any analysis transaction (an LLM call with its
fallbacks), short enough to keep the re-read small."""
"""Default operator-attention severities. ``info`` is intentionally
excluded — see the module docstring.
"""


class AnomalyPageReader(Protocol):
    """The one storage read this feed needs. Satisfied by
    :class:`storage.timescale.briefings.TimescaleBriefingRepository`.
    """

    async def fetch_anomalies_after(
        self,
        session: Any,
        *,
        after: datetime | None,
        severities: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[FindingRow]: ...

    async def fetch_anomalies_between(
        self,
        session: Any,
        *,
        after: datetime,
        until: datetime,
        severities: Iterable[str] | None = None,
        exclude_ids: Iterable[int] = (),
        limit: int = 1000,
    ) -> list[FindingRow]: ...


class AnalysisFindingsAnomalyFeed:
    """Concrete observation feed reading anomaly findings.

    Constructor takes:

      * ``session_factory`` — callable returning an async context
        manager that yields an :class:`AsyncSession`. Production passes
        ``server.db.session.async_session``; tests pass a fake.
      * ``briefing_repo`` — anything with
        :meth:`AnomalyPageReader.fetch_anomalies_after`. Defaults to the
        module-level ``storage.timescale.briefings.default_repository``
        so v0 callers don't need injection.
      * ``severities`` — allowlist of severities surfaced as
        observations. Defaults to :data:`DEFAULT_SEVERITIES`.
      * ``limit`` — findings per fetch. Caps how many proposals one tick
        can emit (also caps the supervisor's blast radius if the database
        backfills a huge batch); a page goes past it only to finish the
        last ``created_at`` group.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        briefing_repo: AnomalyPageReader | None = None,
        severities: Iterable[str] = DEFAULT_SEVERITIES,
        limit: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._briefing_repo: AnomalyPageReader = briefing_repo or default_briefing_repository
        self._severities = tuple(severities)
        self._limit = limit
        # Findings the supervisor acknowledged inside the late-commit window:
        # id -> created_at. Pruned as the cursor moves on.
        self._delivered: dict[int, datetime] = {}

    async def fetch_since(
        self,
        *,
        owner_id: UUID,
        cursor: datetime | None,
    ) -> list[Observation]:
        """Return the oldest anomaly findings created strictly after
        ``cursor`` as :class:`Observation` instances, ascending by
        ``created_at``.

        ``owner_id`` is currently unused — single-user-mode
        ``analysis_findings`` rows don't carry an explicit owner
        column yet. Phase 9+ multi-tenant work will route this through
        the briefing repo. Carrying it now keeps the
        :class:`agents.supervisor.ObservationFeed` Protocol signature
        stable across that change.
        """
        async with self._session_factory() as session:
            rows = await self._briefing_repo.fetch_anomalies_after(
                session,
                after=cursor,
                severities=self._severities,
                limit=self._limit,
            )
            if cursor is not None:
                window_start = cursor - LATE_COMMIT_WINDOW
                self._delivered = {
                    finding_id: created_at
                    for finding_id, created_at in self._delivered.items()
                    if created_at > window_start
                }
                rows = list(rows) + list(
                    await self._briefing_repo.fetch_anomalies_between(
                        session,
                        after=window_start,
                        until=cursor,
                        severities=self._severities,
                        exclude_ids=self._delivered.keys(),
                    )
                )

        # The repo already returns oldest first; sorting again keeps the
        # supervisor's max(occurred_at) cursor correct even if a future
        # repo implementation changes its ORDER BY.
        ordered = sorted(rows, key=lambda r: (r.created_at, r.id))
        return [_row_to_observation(row) for row in ordered]

    def acknowledge(self, observations: list[Observation]) -> None:
        """The supervisor committed the tick that carried ``observations``.

        Remembered so the late-commit re-read (contract 4) does not feed them
        again. Called only after the commit, so a failed tick is re-fed.
        """
        for observation in observations:
            if observation.subject_id is not None:
                self._delivered[int(observation.subject_id)] = observation.occurred_at


def _row_to_observation(row: Any) -> Observation:
    """Map a :class:`storage.timescale.briefings.FindingRow` to the
    :class:`agents.supervisor.Observation` shape the plugin consumes.

    ``subject_id`` is the stringified row id — feeds into the
    supervisor's idempotency key suffix
    (``plugin_id:action_kind:subject_id``). Stringification is required
    because the action_proposals.idempotency_key column is text.
    """
    return Observation(
        subject_id=str(row.id),
        occurred_at=row.created_at,
        payload={
            "finding_id": str(row.id),
            "metric": row.metric,
            "severity": row.severity,
            "structured_data": row.structured_data,
        },
    )


__all__ = [
    "DEFAULT_SEVERITIES",
    "AnalysisFindingsAnomalyFeed",
    "AnomalyPageReader",
]
