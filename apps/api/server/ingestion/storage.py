"""Pluggable ingest storage backends.

Two protocols, by design:

  * ``IngestStorage`` — what every backend MUST implement: resolve a
    device identity, persist samples for a metric. Backend-agnostic
    types (the ``session`` parameter is opaque ``Any`` so a backend
    can use a SQLAlchemy AsyncSession, an httpx Client, or nothing
    at all).

  * ``AuditLog`` — OPTIONAL capability. Postgres ships an audit log
    (``raw_ingestion_log``); InfluxDB is append-only and has no
    UPDATE, so it can't implement this protocol cleanly. The route
    treats audit logging as best-effort: if the configured backend
    provides an ``audit_log``, every batch is logged + marked
    processed; if not, the route skips silently.

Default wiring: the lifespan (``server.main``) creates a
``PostgresIngestStorage`` and a ``PostgresAuditLog`` and stashes
both on ``app.state``. Tests that hit routes without a full app
fall back to module-level singletons.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from . import handlers


@runtime_checkable
class IngestStorage(Protocol):
    """Minimum surface every storage backend must implement."""

    async def get_or_create_device(self, session: Any, device_type: str) -> int | str:
        """Resolve a ``device_type`` label to a backend-specific identity.

        TimescaleDB returns the auto-incrementing ``devices.id`` (int).
        InfluxDB-style backends can return the device_type string itself
        (no ID column needed since identity flows through tags).
        """

    async def ingest_metric(
        self,
        session: Any,
        device_id: int | str,
        metric: str,
        samples: list[dict],
        owner_id: UUID,
    ) -> int:
        """Persist parsed samples; return the count of records written."""


@runtime_checkable
class AuditLog(Protocol):
    """Optional capability: persist + mark raw ingest payloads.

    This is a Postgres-shaped concern (auto-incrementing ID, UPDATE on
    a status column). Append-only backends like InfluxDB do not need
    to implement it; the route falls back to skipping audit calls.
    """

    async def log_raw(
        self,
        session: Any,
        device_id: int | str | None,
        raw_payload: dict,
    ) -> Any:
        """Record the raw inbound payload. Return value is an opaque
        token the route hands back to ``mark_processed``."""

    async def mark_processed(self, session: Any, raw_log_id: Any) -> None:
        """Flip the audit row to processed=true after the batch commit."""


class PostgresIngestStorage:
    """Default backend — TimescaleDB via the existing handlers.

    Each method delegates to the equivalent function in
    ``server.ingestion.handlers``. No SQL changes, no behavior change.
    """

    async def get_or_create_device(self, session: Any, device_type: str) -> int:
        return await handlers._get_or_create_device(session, device_type)

    async def ingest_metric(
        self,
        session: Any,
        device_id: int | str,
        metric: str,
        samples: list[dict],
        owner_id: UUID,
    ) -> int:
        return await handlers._ingest_metric(session, device_id, metric, samples, owner_id)


class PostgresAuditLog:
    """Postgres-only audit log backed by the ``raw_ingestion_log`` table."""

    async def log_raw(
        self,
        session: Any,
        device_id: int | str | None,
        raw_payload: dict,
    ) -> int | None:
        return await handlers._log_raw_ingestion(session, device_id, raw_payload)

    async def mark_processed(self, session: Any, raw_log_id: Any) -> None:
        await handlers._mark_raw_ingestion_processed(session, raw_log_id)


# Module-level defaults — the route falls back to these when
# ``app.state.storage`` / ``app.state.audit_log`` are unset (e.g. in
# unit tests that construct routes directly without a full FastAPI
# lifespan). Production wiring sets both in ``server.main``.
default_storage: IngestStorage = PostgresIngestStorage()
default_audit_log: AuditLog | None = PostgresAuditLog()
