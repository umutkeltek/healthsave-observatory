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

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def fetch_raw_payloads(
    session: AsyncSession,
    *,
    source_type: str | None = "healthsave",
    after_id: int = 0,
    limit: int = 500,
) -> list[tuple[int, dict]]:
    """Read stored raw ingest payloads for replay, oldest first.

    Returns ``(raw_ingestion_log.id, raw_payload)`` tuples. ``after_id`` is an
    ascending-id cursor so a backfill can page across the whole table without
    holding it all in memory. The replay orchestrator (``replay.orchestrator``)
    feeds each ``raw_payload`` straight back through the normalizer — this is
    the read half of ADR-0001 Decision H.
    """
    where = "WHERE id > :after_id"
    params: dict[str, Any] = {"after_id": after_id, "limit": limit}
    if source_type is not None:
        where += " AND source_type = :source_type"
        params["source_type"] = source_type
    sql = text(
        f"""
        SELECT id, raw_payload
          FROM raw_ingestion_log
          {where}
         ORDER BY id ASC
         LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    out: list[tuple[int, dict]] = []
    for row in rows:
        payload = row["raw_payload"]
        if isinstance(payload, str):  # JSONB usually decodes to dict; be defensive
            payload = json.loads(payload)
        out.append((row["id"], payload))
    return out


async def ingest_owner_ids(session: AsyncSession) -> set[UUID]:
    """Every owner that holds an API key or has a sync receipt.

    ``raw_ingestion_log`` has no ``owner_id``, so a raw replay can attribute
    rows to one owner only when nobody else could have sent them. Participant
    keys live in ``api_keys`` (029); every batch since migration 024 leaves an
    owner on its receipt. A database from before 029 has no ``api_keys``
    table, and then only the receipts are read.
    """
    has_api_keys = (
        await session.execute(text("SELECT to_regclass('api_keys') IS NOT NULL"))
    ).scalar_one()
    keys_sql = "SELECT owner_id FROM api_keys UNION " if has_api_keys else ""
    rows = await session.execute(
        text(
            f"""
            {keys_sql}SELECT DISTINCT owner_id FROM healthsave_sync_receipts
             WHERE owner_id IS NOT NULL
            """
        )
    )
    return {UUID(str(row[0])) for row in rows.all()}


async def fetch_raw_metric_payloads(
    session: AsyncSession,
    *,
    wire_metric: str,
    after_id: int = 0,
    limit: int = 500,
) -> list[tuple[int, dict, UUID | None]]:
    """Stored raw batches of ONE wire metric, oldest first, with their owner.

    Returns ``(raw_ingestion_log.id, raw_payload, owner_id)``. The raw log has
    no owner column; the owner is the one the batch's sync receipt recorded
    (``healthsave_sync_receipts.raw_log_id``), or ``None`` when no receipt
    names one. The metric back-fill (``replay.orchestrator``) uses it so a
    participant's batch is never written into the primary person's history.
    """

    sql = text(
        """
        SELECT raw.id,
               raw.raw_payload,
               (SELECT r.owner_id
                  FROM healthsave_sync_receipts AS r
                 WHERE r.raw_log_id = raw.id
                   AND r.owner_id IS NOT NULL
                 ORDER BY r.id
                 LIMIT 1) AS owner_id
          FROM raw_ingestion_log AS raw
         WHERE raw.id > :after_id
           AND raw.source_type = 'healthsave'
           AND raw.raw_payload->>'metric' = :wire_metric
         ORDER BY raw.id ASC
         LIMIT :limit
        """
    )
    rows = (
        (
            await session.execute(
                sql, {"after_id": after_id, "wire_metric": wire_metric, "limit": limit}
            )
        )
        .mappings()
        .all()
    )
    out: list[tuple[int, dict, UUID | None]] = []
    for row in rows:
        payload = row["raw_payload"]
        if isinstance(payload, str):  # JSONB usually decodes to dict; be defensive
            payload = json.loads(payload)
        owner = row["owner_id"]
        out.append((row["id"], payload, UUID(str(owner)) if owner is not None else None))
    return out


async def supersede_metric_records(
    session: AsyncSession,
    *,
    owner_id: UUID,
    metric_id: str,
    uuids: list[str],
) -> int:
    """Mark ONE canonical metric's active rows superseded for these sample UUIDs.

    The back-fill's deletion replay: scoped to ``metric_id`` so it can never
    touch another metric's rows (RMSSD's back-fill never touches SDNN).
    Idempotent; returns rows changed.
    """

    if not uuids:
        return 0
    result = await session.execute(
        text(
            """
            UPDATE canonical_observations
               SET status = 'superseded'
             WHERE owner_id = :owner_id
               AND metric_id = :metric_id
               AND status = 'active'
               AND source_record_uid = ANY(:uuids)
            """
        ),
        {"owner_id": str(owner_id), "metric_id": metric_id, "uuids": list(uuids)},
    )
    return result.rowcount or 0


async def metric_row_counts(
    session: AsyncSession,
    *,
    canonical_metric: str,
    wire_metric: str | None = None,
) -> dict[str, int]:
    """Row counts for one metric: raw projection rows and canonical rows by status."""

    raw = 0
    if wire_metric is not None:
        raw = (
            await session.execute(
                text("SELECT count(*) FROM quantity_samples WHERE metric_name = :wire"),
                {"wire": wire_metric},
            )
        ).scalar_one()
    by_status = (
        await session.execute(
            text(
                """
                SELECT status, count(*) AS n
                  FROM canonical_observations
                 WHERE metric_id = :metric
                 GROUP BY status
                """
            ),
            {"metric": canonical_metric},
        )
    ).all()
    counts = {str(status): int(n) for status, n in by_status}
    return {
        "raw_rows": int(raw),
        "active": counts.get("active", 0),
        "other_status": sum(n for status, n in counts.items() if status != "active"),
    }


async def rows_tagged_with_run(session: AsyncSession, *, run_id: UUID) -> dict[str, int]:
    """Canonical rows a replay run wrote, per metric (its ``normalization_run_id``)."""

    rows = (
        await session.execute(
            text(
                """
                SELECT metric_id, count(*) AS n
                  FROM canonical_observations
                 WHERE normalization_run_id = :run_id
                 GROUP BY metric_id
                """
            ),
            {"run_id": str(run_id)},
        )
    ).all()
    return {str(metric): int(n) for metric, n in rows}


async def fetch_whoop_legacy_recovery_rows(
    session: AsyncSession,
    *,
    device_type: str = "Whoop",
    source_tag: str = "Whoop",
) -> list[tuple[UUID, str, Any, float]]:
    """Whoop recovery readings the per-metric tables hold, oldest first.

    Returns ``(owner_id, kind, time, value)`` with ``kind`` one of ``hrv_rmssd``,
    ``resting_heart_rate``, ``blood_oxygen``. Only rows the Whoop connector
    wrote: device ``Whoop`` AND source ``Whoop``, so an Apple Watch or iPhone
    row (even one HealthKit got from the Whoop app) is never read. Whoop HRV
    sits in ``hrv`` (versions up to 1.5.2 stored it there, mislabelled SDNN)
    or in ``quantity_samples`` (1.5.3); both are RMSSD.
    """

    sql = text(
        """
        WITH whoop AS (SELECT id FROM devices WHERE device_type = :device_type)
        SELECT owner_id, 'hrv_rmssd' AS kind, time, value_ms AS value
          FROM hrv
         WHERE device_id IN (SELECT id FROM whoop) AND source_id = :source_tag
        UNION ALL
        SELECT owner_id,
               CASE metric_name WHEN 'heart_rate_variability_rmssd' THEN 'hrv_rmssd'
                                ELSE 'resting_heart_rate' END,
               time, value
          FROM quantity_samples
         WHERE device_id IN (SELECT id FROM whoop) AND source_id = :source_tag
           AND metric_name IN ('heart_rate_variability_rmssd', 'resting_heart_rate')
        UNION ALL
        SELECT owner_id, 'blood_oxygen', time, spo2_pct
          FROM blood_oxygen
         WHERE device_id IN (SELECT id FROM whoop) AND source_id = :source_tag
         ORDER BY time, kind
        """
    )
    rows = await session.execute(sql, {"device_type": device_type, "source_tag": source_tag})
    return [
        (UUID(str(row.owner_id)), str(row.kind), row.time, float(row.value)) for row in rows.all()
    ]


# Module-level defaults — production wiring (``server.main``) constructs
# its own instances; these are the fallback for unit tests that hit
# routes without a full FastAPI lifespan.
default_storage = PostgresIngestStorage()
default_audit_log: PostgresAuditLog | None = PostgresAuditLog()
