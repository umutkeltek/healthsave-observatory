"""TimescaleDB-backed ingest storage + audit log.

Implements :class:`storage.ports.IngestStorage` and
:class:`storage.ports.AuditLog`. Both classes are stateless wrappers
around the existing handler functions in
``apps/api/server/ingestion/handlers``; that module still owns the
per-metric SQL today. A future phase (5D) lifts that SQL into this
package too, removing the cross-package import.

Until then, :func:`PostgresIngestStorage.ingest_metric` and friends
delegate to the handler functions; the surface this module exposes is
identical to the v1 ``server.ingestion.storage`` shape, which has been
converted into a backwards-compat shim that re-exports from here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from storage.results import IngestWriteResult

# NOTE: ``measurements`` is imported *lazily* inside each method below.
# Eager import here re-introduces a circular import:
#   storage.timescale.ingest → storage.timescale.measurements
#       → server.ingestion.mappers (triggers server.__init__)
#       → server.api.ingest → server.ingestion.storage (shim)
#       → storage.timescale.ingest (partially loaded — boom)
# The cycle disappears once ``server.__init__`` stops re-exporting
# ``server.api.ingest`` (or once ``mappers``/``parsers``/``owner`` move
# out of ``server.ingestion``). Until then, lazy import is the cheapest
# break.


class PostgresIngestStorage:
    """TimescaleDB-backed :class:`storage.ports.IngestStorage`.

    Each method delegates to the corresponding function in
    :mod:`storage.timescale.measurements`. Phase 5E lifted the SQL out
    of ``server.ingestion.handlers`` into measurements; the lazy import
    here breaks the cycle that the cross-package helper imports
    (``mappers``/``parsers``/``owner`` still under ``server.ingestion``)
    would otherwise re-introduce.
    """

    async def get_or_create_device(self, session: Any, device_type: str) -> int:
        from . import measurements

        return await measurements._get_or_create_device(session, device_type)

    async def ingest_metric(
        self,
        session: Any,
        device_id: int | str,
        metric: str,
        samples: list[dict],
        owner_id: UUID,
    ) -> IngestWriteResult:
        from . import measurements

        return await measurements._ingest_metric(session, device_id, metric, samples, owner_id)


class PostgresAuditLog:
    """Postgres-only audit log backed by the ``raw_ingestion_log`` table.

    InfluxDB-style append-only backends do not implement this protocol;
    the ingest route falls back to skipping audit calls when
    ``app.state.audit_log`` is ``None``.
    """

    async def log_raw(
        self,
        session: Any,
        device_id: int | str | None,
        raw_payload: dict,
    ) -> int | None:
        from . import measurements

        return await measurements._log_raw_ingestion(session, device_id, raw_payload)

    async def mark_processed(self, session: Any, raw_log_id: Any) -> None:
        from . import measurements

        await measurements._mark_raw_ingestion_processed(session, raw_log_id)


# Module-level defaults — production wiring (``server.main``) constructs
# its own instances; these are the fallback for unit tests that hit
# routes without a full FastAPI lifespan.
default_storage = PostgresIngestStorage()
default_audit_log: PostgresAuditLog | None = PostgresAuditLog()
