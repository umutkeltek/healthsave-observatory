"""Concrete :class:`agents.supervisor.ObservationFeed` for the
anomaly-watcher plugin.

Reads ``analysis_findings`` via :class:`storage.ports.BriefingRepository`
(:func:`storage.timescale.briefings.fetch_anomalies` under the hood),
filters to operator-attention severities (``watch`` + ``alert``), and
converts each :class:`storage.timescale.briefings.FindingRow` to an
:class:`agents.supervisor.Observation`.

Two contracts this feed enforces:

  1. **Severity allowlist.** The default is ``("watch", "alert")`` —
     ``info`` is intentionally excluded because that's the "noted but
     not actionable" tier from
     :func:`packages.py.analysis.statistical.anomaly._severity_for`.
     Operators can override via the feed constructor when tuning.
  2. **Ascending order.** The supervisor advances its cursor as
     ``max(observation.occurred_at)``, which is only correct if
     observations are returned in ascending ``created_at`` order. The
     underlying ``fetch_anomalies`` returns newest first; we reverse
     before yielding.

The feed opens its own short-lived session via the injected
``session_factory`` — the supervisor's tick reuses the factory for the
persist phase, but each phase gets its own session. No long-lived
transactions span observe + propose + persist.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from agents.supervisor import Observation
from storage.ports import BriefingRepository
from storage.timescale.briefings import default_repository as default_briefing_repository

log = logging.getLogger("healthsave.plugins.anomaly_watcher.feed")


DEFAULT_SEVERITIES: tuple[str, ...] = ("watch", "alert")
"""Default operator-attention severities. ``info`` is intentionally
excluded — see the module docstring.
"""


class AnalysisFindingsAnomalyFeed:
    """Concrete observation feed reading anomaly findings.

    Constructor takes:

      * ``session_factory`` — callable returning an async context
        manager that yields an :class:`AsyncSession`. Production passes
        ``server.db.session.async_session``; tests pass a fake.
      * ``briefing_repo`` — :class:`storage.ports.BriefingRepository`
        Protocol. Defaults to the module-level
        ``storage.timescale.briefings.default_repository`` so v0
        callers don't need injection.
      * ``severities`` — allowlist of severities surfaced as
        observations. Defaults to :data:`DEFAULT_SEVERITIES`.
      * ``limit`` — max findings per fetch. Caps how many proposals
        one tick can emit (also caps the supervisor's blast radius if
        the database backfills a huge batch).
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        briefing_repo: BriefingRepository | None = None,
        severities: Iterable[str] = DEFAULT_SEVERITIES,
        limit: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._briefing_repo: BriefingRepository = briefing_repo or default_briefing_repository
        self._severities = tuple(severities)
        self._limit = limit

    async def fetch_since(
        self,
        *,
        owner_id: UUID,
        cursor: datetime | None,
    ) -> list[Observation]:
        """Read anomaly findings since ``cursor`` and return them as
        :class:`Observation` instances in ascending ``created_at``
        order.

        ``owner_id`` is currently unused — single-user-mode
        ``analysis_findings`` rows don't carry an explicit owner
        column yet. Phase 9+ multi-tenant work will route this through
        the briefing repo. Carrying it now keeps the
        :class:`agents.supervisor.ObservationFeed` Protocol signature
        stable across that change.
        """
        async with self._session_factory() as session:
            rows = await self._briefing_repo.fetch_anomalies(
                session,
                since=cursor,
                severities=self._severities,
                limit=self._limit,
            )

        # fetch_anomalies returns newest-first (matches the dashboard
        # default); supervisor's cursor advance assumes ascending. Don't
        # rely on Python list-reverse equaling SQL ORDER BY: sort
        # explicitly by created_at so the contract is robust to a future
        # query-shape change in the repo.
        ordered = sorted(rows, key=lambda r: r.created_at)
        return [_row_to_observation(row) for row in ordered]


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
]
