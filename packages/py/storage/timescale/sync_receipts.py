"""Timescale-backed HealthSave sync receipt queries."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID
from normalization.mappers import DAILY_ACTIVITY_QUANTITY_FIELDS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from storage.timescale.sync_readiness import build_decision_readiness

# GH#14: the catch-all destination is ``quantity_samples`` keyed by the wire
# metric name, but several metrics land elsewhere — dedicated tables, dedicated
# ``daily_activity`` columns, or (for ECG) ``quantity_samples`` under a *derived*
# name. A receipt is recorded under the wire metric name, so if the destination
# side of the coverage join has no matching row the endpoint reports the metric
# as ``receipt_only``/``stale_payload`` and the frozen client resends it forever.
# These entries must mirror the ingest routing in
# ``storage.timescale.measurements._ingest_metric``. ``ECG_DESTINATION_METRIC``
# is the derived ``quantity_samples.metric_name`` that ``_ingest_ecg`` writes;
# it is surfaced under the ``ecg`` receipt name and excluded from the catch-all
# so coverage does not double-count it.
ECG_DESTINATION_METRIC = "ecg_average_heart_rate"

# Metrics rolled up into ``daily_activity`` (keyed by DATE). Their stored sample
# time is midnight, but the client uploads raw within-day samples, so a naive
# destination-vs-receipt comparison always looks "behind" and the client
# resends forever. These get a day-granularity GREATEST() adjustment so coverage
# reports at least the client's own latest sample. ``activity_summaries`` shares
# the same date-keyed table, so it is adjusted alongside the quantity rollups.
DATE_ROLLUP_METRICS: tuple[str, ...] = (
    "activity_summaries",
    *DAILY_ACTIVITY_QUANTITY_FIELDS,
)


_COVERAGE_OWNER = "owner_id = CAST(:owner_id AS UUID)"
_COVERAGE_RECEIPT_OWNER = "(owner_id = CAST(:owner_id AS UUID) OR owner_id IS NULL)"


def _scope_fragment(fragment: str) -> str:
    """Add the ``:owner_id`` predicate to one ``destination_union`` SELECT."""

    head, group, tail = fragment.partition(" GROUP BY")
    if " WHERE " in head:
        head = head.replace(" WHERE ", f" WHERE {_COVERAGE_OWNER} AND ", 1)
    else:
        head = f"{head} WHERE {_COVERAGE_OWNER}"
    return head + group + tail


def _destination_union_sql(scoped: bool = False) -> str:
    """Build the ``destination_union`` CTE body.

    ``scoped=True`` filters every destination table to the ``:owner_id`` bind
    parameter; the default keeps the historical unscoped SQL byte for byte.

    The ``daily_activity`` quantity rollups are derived from the source-of-truth
    mapper (``DAILY_ACTIVITY_QUANTITY_FIELDS``) so a newly added field can never
    silently reopen the GH#14 resend loop — the drift-guard contract test pins
    this set against the ingest routing.
    """

    fragments = [
        # Dedicated tables that store real per-sample timestamps.
        "SELECT 'heart_rate' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM heart_rate "
        "WHERE status = 'active'",
        "SELECT 'heart_rate_variability' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM hrv "
        "WHERE status = 'active'",
        "SELECT 'oxygen_saturation' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM blood_oxygen "
        "WHERE status = 'active'",
        # body_temperature + wrist_temperature share one table with no in-row
        # type discriminator (the writer never sets measurement_type), so both
        # report its max(time).
        "SELECT 'body_temperature' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM body_temperature "
        "WHERE status = 'active'",
        "SELECT 'wrist_temperature' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM body_temperature "
        "WHERE status = 'active'",
        "SELECT 'sleep_analysis' AS metric, count(*) AS row_count, "
        "max(start_time) AS latest_sample_at FROM sleep_sessions "
        "WHERE status = 'active'",
        "SELECT 'workouts' AS metric, count(*) AS row_count, "
        "max(start_time) AS latest_sample_at FROM workouts",
        # ECG lands in quantity_samples under a derived metric_name, not 'ecg'.
        "SELECT 'ecg' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM quantity_samples "
        f"WHERE metric_name = '{ECG_DESTINATION_METRIC}'",
        # Medication dose events have their own dedicated table.
        "SELECT 'medication_dose_event' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM medication_dose_events",
        # activity_summaries → daily_activity (date-keyed rollup).
        "SELECT 'activity_summaries' AS metric, count(*) AS row_count, "
        "max(date)::timestamptz AS latest_sample_at FROM daily_activity",
    ]
    # daily_activity quantity rollups, one per DAILY_ACTIVITY_QUANTITY_FIELDS
    # entry. Filter on the metric's own column so the row_count reflects rows
    # that actually carry this metric (a daily_activity row may hold steps but
    # not floors_climbed, etc.).
    for wire_metric, (column, _converter) in DAILY_ACTIVITY_QUANTITY_FIELDS.items():
        fragments.append(
            f"SELECT '{wire_metric}' AS metric, count(*) AS row_count, "
            f"max(date)::timestamptz AS latest_sample_at FROM daily_activity "
            f"WHERE {column} IS NOT NULL"
        )
    # Catch-all for every other quantity metric (metric_name == wire name). ECG's
    # derived name is surfaced under 'ecg' above, so exclude it here.
    fragments.append(
        "SELECT metric_name AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM quantity_samples "
        f"WHERE metric_name <> '{ECG_DESTINATION_METRIC}' GROUP BY metric_name"
    )
    if scoped:
        fragments = [_scope_fragment(fragment) for fragment in fragments]
    return "\n                UNION ALL\n                ".join(fragments)


def _sync_coverage_query(owner_id: UUID | None = None) -> str:
    """Assemble the full metric-coverage SQL.

    The ``destination_union`` body and the date-rollup metric list are
    interpolated from trusted internal constants (never client input).

    ``owner_id`` scopes receipts and destinations to one person through the
    ``:owner_id`` bind parameter; ``None`` keeps the historical unscoped SQL.
    The default owner also owns receipts with a NULL owner (pre-migration 024).
    """

    receipt_where = ""
    if owner_id is not None:
        receipt_where = (
            f" WHERE {_COVERAGE_RECEIPT_OWNER}"
            if owner_id == DEFAULT_OWNER_ID
            else f" WHERE {_COVERAGE_OWNER}"
        )
    date_rollup_in = ", ".join(f"'{metric}'" for metric in DATE_ROLLUP_METRICS)
    return f"""
            WITH receipt_coverage AS (
                SELECT
                    metric,
                    count(*) AS batches_seen,
                    count(*) FILTER (WHERE status = 'processed') AS batches_processed,
                    count(*) FILTER (WHERE status = 'empty') AS batches_empty,
                    count(*) FILTER (WHERE status = 'failed') AS batches_failed,
                    coalesce(sum(records_received), 0) AS records_received,
                    coalesce(sum(records_accepted), 0) AS records_accepted,
                    sum(records_inserted_new) AS records_inserted_new,
                    sum(records_deduped_existing) AS records_deduped_existing,
                    CASE
                        WHEN count(*) FILTER (
                            WHERE storage_result_level = 'inserted_vs_existing'
                        ) = count(*) THEN 'inserted_vs_existing'
                        ELSE 'accepted_only'
                    END AS storage_result_level,
                    coalesce(sum(records_skipped), 0) AS records_skipped,
                    max(coalesce(completed_at, received_at)) AS newest_receipt_at,
                    -- Only processed batches stored their samples. A failed
                    -- batch's window must not read as delivered: for day-total
                    -- metrics it would stretch the stored day's coverage below.
                    min(sample_min_at) FILTER (
                        WHERE status = 'processed'
                    ) AS receipt_sample_min_at,
                    max(sample_max_at) FILTER (
                        WHERE status = 'processed'
                    ) AS receipt_sample_max_at
                FROM healthsave_sync_receipts{receipt_where}
                GROUP BY metric
            ),
            destination_union AS (
                {_destination_union_sql(scoped=owner_id is not None)}
            ),
            destination_coverage AS (
                SELECT
                    metric,
                    coalesce(sum(row_count), 0) AS destination_row_count,
                    max(latest_sample_at) AS latest_destination_sample_at
                FROM destination_union
                GROUP BY metric
            )
            SELECT
                coalesce(r.metric, d.metric) AS metric,
                coalesce(r.batches_seen, 0) AS batches_seen,
                coalesce(r.batches_processed, 0) AS batches_processed,
                coalesce(r.batches_empty, 0) AS batches_empty,
                coalesce(r.batches_failed, 0) AS batches_failed,
                coalesce(r.records_received, 0) AS records_received,
                coalesce(r.records_accepted, 0) AS records_accepted,
                r.records_inserted_new,
                r.records_deduped_existing,
                coalesce(r.storage_result_level, 'accepted_only') AS storage_result_level,
                coalesce(r.records_skipped, 0) AS records_skipped,
                r.newest_receipt_at,
                r.receipt_sample_min_at,
                r.receipt_sample_max_at,
                coalesce(d.destination_row_count, 0) AS destination_row_count,
                d.latest_destination_sample_at,
                -- GH#14: date-rollup destinations store midnight, so the raw value
                -- reads as "behind" the client's within-day upload and triggers a
                -- perpetual resend. Report at least the client's own latest sample
                -- once the day is actually stored (row present). Guarded on
                -- NOT NULL so a genuinely-unwritten metric still reports
                -- receipt_only and the client correctly retries.
                CASE
                    WHEN coalesce(r.metric, d.metric) IN ({date_rollup_in})
                         AND d.latest_destination_sample_at IS NOT NULL
                    THEN GREATEST(d.latest_destination_sample_at, r.receipt_sample_max_at)
                    ELSE d.latest_destination_sample_at
                END AS adjusted_latest_destination_sample_at
            FROM receipt_coverage r
            FULL OUTER JOIN destination_coverage d ON d.metric = r.metric
            ORDER BY metric
            """


class ReceiptIdempotencyConflict(ValueError):
    """Raised when a retry key is reused with different payload bytes."""


def _receipt_value(row: Any, key: str) -> Any:
    return row.get(key) if hasattr(row, "get") else row[key]


def _frozen_receipt_response(
    row: Any,
    *,
    payload_hash: str,
) -> dict[str, Any] | None:
    """Validate a stored receipt and decode its frozen successful response."""

    existing_hash = _receipt_value(row, "payload_hash")
    if existing_hash != payload_hash:
        raise ReceiptIdempotencyConflict(
            "This idempotency key was already received with a different payload hash."
        )

    status = _receipt_value(row, "status")
    response_payload = _receipt_value(row, "response_payload")
    if status not in {"processed", "empty"} or response_payload is None:
        return None
    if isinstance(response_payload, str):
        try:
            response_payload = json.loads(response_payload)
        except (TypeError, ValueError):
            return None
    return dict(response_payload) if isinstance(response_payload, dict) else None


async def claim_receipt_idempotency(
    session: AsyncSession,
    *,
    owner_id: UUID,
    idempotency_key: str | None,
    payload_hash: str | None,
    metric: str,
    batch_index: int,
    total_batches: int,
) -> dict[str, Any] | None:
    """Atomically reserve an idempotency key or return its frozen response.

    The owner/key unique index is the serialization primitive. A concurrent
    insert blocks on the winner's transaction; after that transaction commits,
    the loser observes either the completed response or a payload conflict.
    Failed, hashless, and incomplete legacy rows may be reclaimed. A returned
    ``None`` means this transaction owns the ``processing`` claim (or that the
    request supplied no usable key/hash); callers must finalize an owned claim
    before committing their ingest writes.
    """

    if not idempotency_key or not payload_hash:
        return None

    claim_result = await session.execute(
        text(
            """
            INSERT INTO healthsave_sync_receipts (
                owner_id,
                idempotency_key,
                payload_hash,
                metric,
                batch_index,
                total_batches,
                status,
                records_received,
                records_accepted,
                records_skipped,
                source_endpoint
            ) VALUES (
                CAST(:owner_id AS UUID),
                :idempotency_key,
                :payload_hash,
                :metric,
                :batch_index,
                :total_batches,
                'processing',
                0,
                0,
                0,
                '/api/apple/batch'
            )
            ON CONFLICT (owner_id, idempotency_key)
                WHERE owner_id IS NOT NULL AND idempotency_key IS NOT NULL
            DO UPDATE SET
                payload_hash = EXCLUDED.payload_hash,
                metric = EXCLUDED.metric,
                batch_index = EXCLUDED.batch_index,
                total_batches = EXCLUDED.total_batches,
                status = 'processing',
                records_received = 0,
                records_accepted = 0,
                records_skipped = 0,
                records_inserted_new = NULL,
                records_deduped_existing = NULL,
                storage_result_level = 'accepted_only',
                sample_min_at = NULL,
                sample_max_at = NULL,
                error_message = NULL,
                raw_log_id = NULL,
                response_payload = NULL,
                completed_at = NULL
            WHERE
                healthsave_sync_receipts.payload_hash IS NULL
                -- A failed attempt stored nothing and froze no response, so it
                -- does not pin the key to its body: any retry may reclaim it.
                OR healthsave_sync_receipts.status = 'failed'
                OR (
                    healthsave_sync_receipts.status IN ('processed', 'empty')
                    AND healthsave_sync_receipts.payload_hash = EXCLUDED.payload_hash
                    AND (
                        healthsave_sync_receipts.response_payload IS NULL
                        OR jsonb_typeof(healthsave_sync_receipts.response_payload) <> 'object'
                    )
                )
            RETURNING payload_hash, status, response_payload
            """
        ),
        {
            "owner_id": str(owner_id),
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "metric": metric,
            "batch_index": batch_index,
            "total_batches": total_batches,
        },
    )
    if claim_result.mappings().first() is not None:
        return None

    existing_result = await session.execute(
        text(
            """
            SELECT payload_hash, status, response_payload
            FROM healthsave_sync_receipts
            WHERE owner_id = CAST(:owner_id AS UUID)
              AND idempotency_key = :idempotency_key
            LIMIT 1
            """
        ),
        {"owner_id": str(owner_id), "idempotency_key": idempotency_key},
    )
    row = existing_result.mappings().first()
    if row is None:
        raise RuntimeError("idempotency claim conflict resolved without a visible receipt row")

    frozen_response = _frozen_receipt_response(row, payload_hash=payload_hash)
    if frozen_response is not None:
        return frozen_response
    raise RuntimeError("idempotency key is already held by an incomplete receipt")


async def complete_receipt_idempotency(
    session: AsyncSession,
    *,
    owner_id: UUID,
    idempotency_key: str,
    payload_hash: str,
    status: str,
    response_payload: dict[str, Any],
    raw_log_id: int | None,
    records_received: int,
    records_accepted: int,
    records_skipped: int,
    records_inserted_new: int | None = None,
    records_deduped_existing: int | None = None,
    storage_result_level: str = "accepted_only",
    sample_min_at: str | None = None,
    sample_max_at: str | None = None,
    sync_run_id: str | None = None,
) -> None:
    """Freeze a claimed response inside the ingest transaction.

    ``sync_run_id`` is written here, in the ingest transaction, so the receipt
    names its run even when the later best-effort enrichment fails.
    """

    if status not in {"processed", "empty"}:
        raise ValueError("a successful idempotency claim must complete as processed or empty")

    result = await session.execute(
        text(
            """
            UPDATE healthsave_sync_receipts
            SET
                status = :status,
                sync_run_id = COALESCE(:sync_run_id, sync_run_id),
                records_received = :records_received,
                records_accepted = :records_accepted,
                records_skipped = :records_skipped,
                records_inserted_new = :records_inserted_new,
                records_deduped_existing = :records_deduped_existing,
                storage_result_level = :storage_result_level,
                sample_min_at = :sample_min_at,
                sample_max_at = :sample_max_at,
                error_message = NULL,
                raw_log_id = :raw_log_id,
                response_payload = CAST(:response_payload AS JSONB),
                completed_at = now()
            WHERE owner_id = CAST(:owner_id AS UUID)
              AND idempotency_key = :idempotency_key
              AND payload_hash = :payload_hash
              AND status = 'processing'
            RETURNING id
            """
        ),
        {
            "owner_id": str(owner_id),
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "status": status,
            "sync_run_id": sync_run_id,
            "records_received": records_received,
            "records_accepted": records_accepted,
            "records_skipped": records_skipped,
            "records_inserted_new": records_inserted_new,
            "records_deduped_existing": records_deduped_existing,
            "storage_result_level": storage_result_level,
            "sample_min_at": _parse_time_value(sample_min_at),
            "sample_max_at": _parse_time_value(sample_max_at),
            "raw_log_id": raw_log_id,
            "response_payload": json.dumps(response_payload, separators=(",", ":")),
        },
    )
    if result.first() is None:
        raise RuntimeError("owned idempotency receipt could not be completed")


async def record_sync_receipt(
    session: AsyncSession,
    *,
    owner_id: UUID,
    sync_run_id: str | None,
    batch_id: str | None,
    idempotency_key: str | None,
    payload_hash: str | None,
    metric: str,
    batch_index: int,
    total_batches: int,
    sync_mode: str | None,
    anchor_present: bool | None,
    lower_bound_reason: str | None,
    full_export: bool | None,
    query_lower_bound_at: str | None,
    status: str,
    records_received: int,
    records_accepted: int,
    records_skipped: int,
    sample_min_at: str | None,
    sample_max_at: str | None,
    raw_log_id: int | None,
    records_inserted_new: int | None = None,
    records_deduped_existing: int | None = None,
    storage_result_level: str = "accepted_only",
    error_message: str | None = None,
    response_payload: dict[str, Any] | None = None,
) -> None:
    """Insert or update one HealthSave batch receipt.

    ``batch_id`` is unique per owner when present so app retries update the
    receipt instead of making the support/operator view look like duplicate
    batches arrived.

    Timestamp inputs (``query_lower_bound_at``, ``sample_min_at``,
    ``sample_max_at``) arrive from iOS as ISO8601 strings via request headers.
    The receipts table columns are ``TIMESTAMPTZ``, so asyncpg refuses to
    encode a raw string and returns ``HTTP 500`` from /api/apple/batch — the
    exact failure mode the deployed Data Hub hit on every quantity-typed
    batch (heart_rate, hrv, blood_oxygen, …) once iOS started sending
    evidence headers in build 28+. Parse them to ``datetime`` before binding;
    leave malformed inputs as ``None`` rather than 500-ing the entire batch.
    """

    parsed_query_lower_bound_at = _parse_time_value(query_lower_bound_at)
    parsed_sample_min_at = _parse_time_value(sample_min_at)
    parsed_sample_max_at = _parse_time_value(sample_max_at)

    await session.execute(
        text(
            """
            INSERT INTO healthsave_sync_receipts
                (
                    owner_id,
                    sync_run_id,
                    batch_id,
                    idempotency_key,
                    payload_hash,
                    metric,
                    batch_index,
                    total_batches,
                    sync_mode,
                    anchor_present,
                    lower_bound_reason,
                    full_export,
                    query_lower_bound_at,
                    status,
                    records_received,
                    records_accepted,
                    records_skipped,
                    records_inserted_new,
                    records_deduped_existing,
                    storage_result_level,
                    sample_min_at,
                    sample_max_at,
                    error_message,
                    raw_log_id,
                    source_endpoint,
                    response_payload,
                    completed_at
                )
            VALUES
                (
                    CAST(:owner_id AS UUID),
                    :sync_run_id,
                    :batch_id,
                    :idempotency_key,
                    :payload_hash,
                    :metric,
                    :batch_index,
                    :total_batches,
                    :sync_mode,
                    :anchor_present,
                    :lower_bound_reason,
                    :full_export,
                    :query_lower_bound_at,
                    :status,
                    :records_received,
                    :records_accepted,
                    :records_skipped,
                    :records_inserted_new,
                    :records_deduped_existing,
                    :storage_result_level,
                    :sample_min_at,
                    :sample_max_at,
                    :error_message,
                    :raw_log_id,
                    :source_endpoint,
                    CAST(:response_payload AS JSONB),
                    now()
                )
            ON CONFLICT (owner_id, idempotency_key)
                WHERE owner_id IS NOT NULL AND idempotency_key IS NOT NULL
            DO UPDATE SET
                sync_run_id = EXCLUDED.sync_run_id,
                batch_id = EXCLUDED.batch_id,
                payload_hash = EXCLUDED.payload_hash,
                metric = EXCLUDED.metric,
                batch_index = EXCLUDED.batch_index,
                total_batches = EXCLUDED.total_batches,
                sync_mode = EXCLUDED.sync_mode,
                anchor_present = EXCLUDED.anchor_present,
                lower_bound_reason = EXCLUDED.lower_bound_reason,
                full_export = EXCLUDED.full_export,
                query_lower_bound_at = EXCLUDED.query_lower_bound_at,
                status = EXCLUDED.status,
                records_received = EXCLUDED.records_received,
                records_accepted = EXCLUDED.records_accepted,
                records_skipped = EXCLUDED.records_skipped,
                records_inserted_new = EXCLUDED.records_inserted_new,
                records_deduped_existing = EXCLUDED.records_deduped_existing,
                storage_result_level = EXCLUDED.storage_result_level,
                sample_min_at = EXCLUDED.sample_min_at,
                sample_max_at = EXCLUDED.sample_max_at,
                error_message = EXCLUDED.error_message,
                raw_log_id = EXCLUDED.raw_log_id,
                response_payload = EXCLUDED.response_payload,
                completed_at = EXCLUDED.completed_at
            WHERE
                (
                    healthsave_sync_receipts.payload_hash IS NULL
                    OR healthsave_sync_receipts.payload_hash
                        IS NOT DISTINCT FROM EXCLUDED.payload_hash
                )
                AND (
                    EXCLUDED.status <> 'failed'
                    OR healthsave_sync_receipts.status = 'failed'
                )
            """
        ),
        {
            "owner_id": str(owner_id),
            "sync_run_id": sync_run_id,
            "batch_id": batch_id,
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "metric": metric,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "sync_mode": sync_mode,
            "anchor_present": anchor_present,
            "lower_bound_reason": lower_bound_reason,
            "full_export": full_export,
            "query_lower_bound_at": parsed_query_lower_bound_at,
            "status": status,
            "records_received": records_received,
            "records_accepted": records_accepted,
            "records_skipped": records_skipped,
            "records_inserted_new": records_inserted_new,
            "records_deduped_existing": records_deduped_existing,
            "storage_result_level": storage_result_level,
            "sample_min_at": parsed_sample_min_at,
            "sample_max_at": parsed_sample_max_at,
            "error_message": error_message,
            "raw_log_id": raw_log_id,
            "source_endpoint": "/api/apple/batch",
            "response_payload": (
                json.dumps(response_payload, separators=(",", ":"))
                if response_payload is not None
                else None
            ),
        },
    )


# ─── Sync run summaries (client-closed runs) ─────────────────────────────
#
# Receipts are written per HTTP batch, so a run that had nothing to send left
# no trace and ``latest_sync_run`` kept returning the PREVIOUS run for as long
# as the app found nothing new. The client now closes every completed run with
# one ``PUT /api/v2/sync/runs/{sync_run_id}/summary`` (migration 026). Receipts
# remain the delivery proof; the summary is the run's existence proof. The two
# readers below merge them so a zero-delivery run is a real, distinguishable
# "latest run" instead of a lie by omission.

SYNC_RUN_SUMMARY_INTENTS: frozenset[str] = frozenset({"latest_changes", "backfill", "date_range"})
SYNC_RUN_SUMMARY_OUTCOMES: frozenset[str] = frozenset({"completed", "failed"})
SYNC_RUN_SUMMARY_DELIVERIES: frozenset[str] = frozenset({"none", "foreground", "background_queued"})

#: ``verification_level`` for a run the server knows only from the client's
#: closing summary — nothing was delivered, so there is no delivery receipt to
#: prove. Distinct from ``delivery_receipt`` on purpose: a consumer must be able
#: to tell "the server saw batches" from "the client said it checked".
RUN_SUMMARY_VERIFICATION_LEVEL = "run_summary"
DELIVERY_RECEIPT_VERIFICATION_LEVEL = "delivery_receipt"

_RUN_SUMMARY_SELECT = """
    SELECT
        sync_run_id,
        client_platform,
        client_app_version,
        trigger,
        intent,
        outcome,
        delivery,
        records_sent,
        metrics_checked,
        metrics_with_changes,
        error_class,
        client_started_at,
        client_completed_at,
        received_at,
        updated_at
    FROM healthsave_sync_run_summaries
"""


async def record_sync_run_summary(
    session: AsyncSession,
    *,
    owner_id: UUID,
    sync_run_id: str,
    outcome: str,
    delivery: str,
    records_sent: int,
    metrics_checked: list[str],
    metrics_with_changes: list[str],
    trigger: str | None,
    intent: str | None,
    error_class: str | None,
    client_platform: str | None,
    client_app_version: str | None,
    client_started_at: str | datetime | None,
    client_completed_at: str | datetime | None,
) -> dict[str, Any]:
    """Insert or replace the closing summary for one HealthSave sync run.

    Idempotent on ``sync_run_id`` — the client may retry the PUT. ``received_at``
    is preserved on conflict (first arrival is the server-stamped run close);
    ``updated_at`` moves. Returns the stored ``received_at``/``updated_at`` so the
    route can echo server-stamped times back to the client.
    """

    result = await session.execute(
        text(
            """
            INSERT INTO healthsave_sync_run_summaries (
                sync_run_id, owner_id, client_platform, client_app_version,
                trigger, intent, outcome, delivery, records_sent,
                metrics_checked, metrics_with_changes, error_class,
                client_started_at, client_completed_at
            ) VALUES (
                :sync_run_id, :owner_id, :client_platform, :client_app_version,
                :trigger, :intent, :outcome, :delivery, :records_sent,
                :metrics_checked, :metrics_with_changes, :error_class,
                :client_started_at, :client_completed_at
            )
            ON CONFLICT (sync_run_id) DO UPDATE SET
                client_platform = EXCLUDED.client_platform,
                client_app_version = EXCLUDED.client_app_version,
                trigger = EXCLUDED.trigger,
                intent = EXCLUDED.intent,
                outcome = EXCLUDED.outcome,
                delivery = EXCLUDED.delivery,
                records_sent = EXCLUDED.records_sent,
                metrics_checked = EXCLUDED.metrics_checked,
                metrics_with_changes = EXCLUDED.metrics_with_changes,
                error_class = EXCLUDED.error_class,
                client_started_at = EXCLUDED.client_started_at,
                client_completed_at = EXCLUDED.client_completed_at,
                updated_at = NOW()
            WHERE healthsave_sync_run_summaries.owner_id = EXCLUDED.owner_id
            RETURNING received_at, updated_at
            """
        ),
        {
            "sync_run_id": sync_run_id,
            "owner_id": str(owner_id),
            "client_platform": client_platform,
            "client_app_version": client_app_version,
            "trigger": trigger,
            "intent": intent,
            "outcome": outcome,
            "delivery": delivery,
            "records_sent": records_sent,
            "metrics_checked": sorted(set(metrics_checked)),
            "metrics_with_changes": sorted(set(metrics_with_changes)),
            "error_class": error_class,
            "client_started_at": _parse_time_value(client_started_at),
            "client_completed_at": _parse_time_value(client_completed_at),
        },
    )
    row = result.mappings().first()
    stamped = dict(row) if row is not None else {}
    return {
        "status": "ok",
        "sync_run_id": sync_run_id,
        # False only when the run id already belongs to another owner: a
        # participant key never overwrites someone else's run summary.
        "recorded": row is not None,
        "received_at": stamped.get("received_at"),
        "updated_at": stamped.get("updated_at"),
    }


def _owner_filter(owner_id: UUID | None) -> tuple[str, dict[str, str]]:
    """``AND`` clause scoping receipt/summary reads to one owner.

    ``None`` keeps the pre-029 unscoped SQL byte for byte. Receipts written
    before migration 024 carry a NULL owner; they were all the default
    owner's, so the default owner's scope includes them and a single-owner
    install answers exactly as before.
    """

    if owner_id is None:
        return "", {}
    if owner_id == DEFAULT_OWNER_ID:
        return (
            " AND (owner_id = CAST(:owner_id AS UUID) OR owner_id IS NULL)",
            {"owner_id": str(owner_id)},
        )
    return " AND owner_id = CAST(:owner_id AS UUID)", {"owner_id": str(owner_id)}


def _format_run_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "sync_run_id": row["sync_run_id"],
        "client_platform": row.get("client_platform"),
        "client_app_version": row.get("client_app_version"),
        "trigger": row.get("trigger"),
        "intent": row.get("intent"),
        "outcome": row.get("outcome"),
        "delivery": row.get("delivery"),
        "records_sent": row.get("records_sent") or 0,
        "metrics_checked": list(row.get("metrics_checked") or []),
        "metrics_with_changes": list(row.get("metrics_with_changes") or []),
        "error_class": row.get("error_class"),
        "client_started_at": row.get("client_started_at"),
        "client_completed_at": row.get("client_completed_at"),
        "received_at": row.get("received_at"),
    }


async def _latest_run_summary(
    session: AsyncSession, owner_id: UUID | None = None
) -> dict[str, Any] | None:
    clause, params = _owner_filter(owner_id)
    sql = _RUN_SUMMARY_SELECT
    if clause:
        sql += " WHERE TRUE" + clause
    result = await session.execute(text(sql + " ORDER BY received_at DESC LIMIT 1"), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _run_summary(
    session: AsyncSession, sync_run_id: str, owner_id: UUID | None = None
) -> dict[str, Any] | None:
    clause, params = _owner_filter(owner_id)
    result = await session.execute(
        text(_RUN_SUMMARY_SELECT + " WHERE sync_run_id = :sync_run_id" + clause),
        {"sync_run_id": sync_run_id, **params},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _evidence_label(has_receipts: bool, has_summary: bool) -> str:
    if has_receipts and has_summary:
        return "delivery_receipts+run_summary"
    if has_receipts:
        return "delivery_receipts"
    return "run_summary"


def _newer(left: Any, right: Any) -> bool:
    """True when ``left`` is strictly newer than ``right`` (None is oldest)."""
    if left is None:
        return False
    if right is None:
        return True
    return _compare_time_values(left, right) > 0


async def latest_sync_run(session: AsyncSession, owner_id: UUID | None = None) -> dict[str, Any]:
    """Summarize the most recently observed HealthSave sync run.

    "Observed" means EITHER the server received batches for it (receipts) OR the
    client closed it with a run summary (migration 026). A run that had nothing
    to send has no receipts, so before the summaries existed this endpoint kept
    answering with the previous run — the Observatory showed an app that syncs
    every 10 minutes as having stopped hours ago. The newest evidence of either
    kind wins, judged by server-stamped time only; when both describe the same
    run they are merged.

    NOTE: every key iOS decodes is emitted from THIS function's source (SQL
    alias, dict literal or item assignment) — ``test_ios_v2_surface.py`` pins
    them here. Keep the SQL and the zero-delivery literal inline.
    """
    owner_clause, owner_params = _owner_filter(owner_id)

    result = await session.execute(
        text(
            f"""
            SELECT sync_run_id
            FROM healthsave_sync_receipts
            WHERE sync_run_id IS NOT NULL{owner_clause}
            ORDER BY received_at DESC, id DESC
            LIMIT 1
            """
        ),
        owner_params,
    )
    row = result.mappings().first()
    receipt_run: dict[str, Any] | None = None
    if row is not None:
        summary_result = await session.execute(
            text(
                f"""
                SELECT
                    sync_run_id,
                    min(received_at) AS started_at,
                    max(coalesce(completed_at, received_at)) AS completed_at,
                    count(*) AS batches_seen,
                    count(*) FILTER (WHERE status = 'processed') AS batches_processed,
                    count(*) FILTER (WHERE status = 'empty') AS batches_empty,
                    count(*) FILTER (WHERE status = 'failed') AS batches_failed,
                    coalesce(sum(records_received), 0) AS records_received,
                    coalesce(sum(records_accepted), 0) AS records_accepted,
                    sum(records_inserted_new) AS records_inserted_new,
                    sum(records_deduped_existing) AS records_deduped_existing,
                    CASE
                        WHEN count(*) FILTER (
                            WHERE storage_result_level = 'inserted_vs_existing'
                        ) = count(*) THEN 'inserted_vs_existing'
                        ELSE 'accepted_only'
                    END AS storage_result_level,
                    coalesce(sum(records_skipped), 0) AS records_skipped,
                    min(sample_min_at) AS sample_min_at,
                    max(sample_max_at) AS sample_max_at,
                    array_agg(DISTINCT metric ORDER BY metric) AS metrics
                FROM healthsave_sync_receipts
                WHERE sync_run_id = :sync_run_id{owner_clause}
                GROUP BY sync_run_id
                """
            ),
            {"sync_run_id": row["sync_run_id"], **owner_params},
        )
        summary_row = summary_result.mappings().first()
        receipt_run = dict(summary_row) if summary_row is not None else None

    latest_summary = await _latest_run_summary(session, owner_id)

    if receipt_run is None and latest_summary is None:
        return {"status": "empty", "message": "No HealthSave sync receipts recorded yet."}

    # Which run is "latest": the receipt run's newest receipt vs the summary's
    # arrival, both server-stamped. Client clocks never participate.
    receipt_time = receipt_run["completed_at"] if receipt_run is not None else None
    summary_time = latest_summary["received_at"] if latest_summary is not None else None

    if receipt_run is not None and (
        latest_summary is None
        or latest_summary["sync_run_id"] == receipt_run["sync_run_id"]
        or not _newer(summary_time, receipt_time)
    ):
        summary = dict(receipt_run)
        same_run = (
            latest_summary is not None
            and latest_summary["sync_run_id"] == receipt_run["sync_run_id"]
        )
        if same_run:
            run_summary = latest_summary
        else:
            run_summary = await _run_summary(session, receipt_run["sync_run_id"], owner_id)
        summary["evidence"] = _evidence_label(True, run_summary is not None)
    else:
        assert latest_summary is not None
        # Zero-delivery run: the client checked and had nothing to send (or its
        # batches are still in flight on a background session and no receipt
        # has landed yet — the next poll merges them in). Zero, not null:
        # nothing was delivered, so there is nothing to be unsure about.
        # ``storage_result_level`` is vacuously ``inserted_vs_existing``; the
        # iOS decoder renders that as "0 new, 0 existing" — exactly the truth.
        run_summary = latest_summary
        summary = {
            "sync_run_id": latest_summary["sync_run_id"],
            "started_at": latest_summary.get("client_started_at") or latest_summary["received_at"],
            "completed_at": latest_summary["received_at"],
            "batches_seen": 0,
            "batches_processed": 0,
            "batches_empty": 0,
            "batches_failed": 0,
            "records_received": 0,
            "records_accepted": 0,
            "records_inserted_new": 0,
            "records_deduped_existing": 0,
            "storage_result_level": "inserted_vs_existing",
            "records_skipped": 0,
            "sample_min_at": None,
            "sample_max_at": None,
            "metrics": [],
            "evidence": _evidence_label(False, True),
        }

    summary["status"] = "ok"
    summary["sample_window"] = _sample_window(summary)
    summary["latest_sample_time"] = summary["sample_max_at"]
    summary["run_summary"] = _format_run_summary(run_summary)
    return summary


async def sync_run(
    session: AsyncSession, sync_run_id: str, owner_id: UUID | None = None
) -> dict[str, Any]:
    """Return a receipt-level summary for one HealthSave sync run.

    This is a delivery receipt summary: it proves Data Hub saw and accepted
    batches for the run. It does not claim manifest-level sample verification.
    """
    owner_clause, owner_params = _owner_filter(owner_id)

    result = await session.execute(
        text(
            f"""
            SELECT
                metric,
                min(received_at) AS started_at,
                max(coalesce(completed_at, received_at)) AS completed_at,
                count(*) AS batches_seen,
                count(*) FILTER (WHERE status = 'processed') AS batches_processed,
                count(*) FILTER (WHERE status = 'empty') AS batches_empty,
                count(*) FILTER (WHERE status = 'failed') AS batches_failed,
                coalesce(sum(records_received), 0) AS records_received,
                coalesce(sum(records_accepted), 0) AS records_accepted,
                sum(records_inserted_new) AS records_inserted_new,
                sum(records_deduped_existing) AS records_deduped_existing,
                CASE
                    WHEN count(*) FILTER (
                        WHERE storage_result_level = 'inserted_vs_existing'
                    ) = count(*) THEN 'inserted_vs_existing'
                    ELSE 'accepted_only'
                END AS storage_result_level,
                coalesce(sum(records_skipped), 0) AS records_skipped,
                min(sample_min_at) AS sample_min_at,
                max(sample_max_at) AS sample_max_at,
                max(sample_max_at) AS latest_sample_at
            FROM healthsave_sync_receipts
            WHERE sync_run_id = :sync_run_id{owner_clause}
            GROUP BY metric
            ORDER BY metric
            """
        ),
        {"sync_run_id": sync_run_id, **owner_params},
    )
    rows = [dict(row) for row in result.mappings().all()]
    run_summary = await _run_summary(session, sync_run_id, owner_id)
    if not rows:
        if run_summary is None:
            return {
                "status": "empty",
                "sync_run_id": sync_run_id,
                "message": "No HealthSave sync receipts recorded for this run.",
            }
        # The client closed this run without sending a single batch. That is
        # a real, complete run — not "no receipt yet" — so it must NOT decode
        # as the empty sentinel (iOS treats ``status: empty`` as "nothing
        # known about this run" and keeps waiting).
        return {
            "status": "ok",
            "sync_run_id": sync_run_id,
            "verification_level": RUN_SUMMARY_VERIFICATION_LEVEL,
            "evidence": _evidence_label(False, True),
            "started_at": run_summary.get("client_started_at") or run_summary["received_at"],
            "completed_at": run_summary["received_at"],
            "summary": {
                "metrics_seen": 0,
                "batches_seen": 0,
                "batches_processed": 0,
                "batches_empty": 0,
                "batches_failed": 0,
                "records_received": 0,
                "records_accepted": 0,
                "records_inserted_new": 0,
                "records_deduped_existing": 0,
                "storage_result_level": "inserted_vs_existing",
                "records_rejected": 0,
                "sample_window": {"min_sample_time": None, "max_sample_time": None},
            },
            "per_metric": {},
            "run_summary": _format_run_summary(run_summary),
        }

    per_metric = {
        row["metric"]: {
            "batches_seen": row["batches_seen"],
            "batches_processed": row["batches_processed"],
            "batches_empty": row["batches_empty"],
            "batches_failed": row["batches_failed"],
            "received": row["records_received"],
            "accepted": row["records_accepted"],
            "inserted_new": row.get("records_inserted_new"),
            "deduped_existing": row.get("records_deduped_existing"),
            "storage_result_level": row.get("storage_result_level", "accepted_only"),
            "rejected": row["records_skipped"],
            "sample_window": _sample_window(row),
            "latest_sample_time": row["latest_sample_at"],
        }
        for row in rows
    }
    return {
        "status": "ok",
        "sync_run_id": sync_run_id,
        "verification_level": DELIVERY_RECEIPT_VERIFICATION_LEVEL,
        "evidence": _evidence_label(True, run_summary is not None),
        "run_summary": _format_run_summary(run_summary),
        "started_at": min(row["started_at"] for row in rows if row["started_at"] is not None),
        "completed_at": max(row["completed_at"] for row in rows if row["completed_at"] is not None),
        "summary": {
            "metrics_seen": len(rows),
            "batches_seen": sum(row["batches_seen"] for row in rows),
            "batches_processed": sum(row["batches_processed"] for row in rows),
            "batches_empty": sum(row["batches_empty"] for row in rows),
            "batches_failed": sum(row["batches_failed"] for row in rows),
            "records_received": sum(row["records_received"] for row in rows),
            "records_accepted": sum(row["records_accepted"] for row in rows),
            "records_inserted_new": _sum_optional(row.get("records_inserted_new") for row in rows),
            "records_deduped_existing": _sum_optional(
                row.get("records_deduped_existing") for row in rows
            ),
            "storage_result_level": _combined_storage_result_level(rows),
            "records_rejected": sum(row["records_skipped"] for row in rows),
            "sample_window": {
                "min_sample_time": min(
                    (row["sample_min_at"] for row in rows if row["sample_min_at"] is not None),
                    default=None,
                ),
                "max_sample_time": max(
                    (row["sample_max_at"] for row in rows if row["sample_max_at"] is not None),
                    default=None,
                ),
            },
        },
        "per_metric": per_metric,
    }


async def sync_coverage(session: AsyncSession, owner_id: UUID | None = None) -> dict[str, Any]:
    """Return metric-level receipt and destination sample coverage.

    ``owner_id=None`` is the historical all-rows read (the phone-facing sync
    routes); the Home Assistant bridge passes its owner.
    """

    if owner_id is None:
        result = await session.execute(text(_sync_coverage_query()))
    else:
        result = await session.execute(
            text(_sync_coverage_query(owner_id)), {"owner_id": str(owner_id)}
        )
    rows = [_format_coverage_row(dict(row)) for row in result.mappings().all()]
    decision_readiness = build_decision_readiness(rows)
    return {
        "status": "ok",
        "summary": {
            "metrics_seen": len(rows),
            "batches_seen": sum(row["batches_seen"] for row in rows),
            "records_received": sum(row["records_received"] for row in rows),
            "records_accepted": sum(row["records_accepted"] for row in rows),
            "records_inserted_new": _sum_optional(row.get("records_inserted_new") for row in rows),
            "records_deduped_existing": _sum_optional(
                row.get("records_deduped_existing") for row in rows
            ),
            "records_skipped": sum(row["records_skipped"] for row in rows),
        },
        "metrics": rows,
        "decision_readiness": decision_readiness,
    }


def _sample_window(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "min_sample_time": row.get("sample_min_at") or row.get("receipt_sample_min_at"),
        "max_sample_time": row.get("sample_max_at") or row.get("receipt_sample_max_at"),
    }


def _format_coverage_row(row: dict[str, Any]) -> dict[str, Any]:
    receipt_sample_max = row.get("receipt_sample_max_at")
    # GH#14: prefer the day-granularity-adjusted destination timestamp. The iOS
    # client keys its resend decision on ``latest_destination_sample_time``
    # (BackendCompatibility.swift) and never reads ``freshness_state``, so the
    # adjusted value must flow into the reported field — not just the internal
    # freshness label. Fall back to the raw column when the query did not emit
    # an adjusted value (e.g. mocked rows in unit tests).
    destination_sample = row.get("adjusted_latest_destination_sample_at")
    if destination_sample is None:
        destination_sample = row.get("latest_destination_sample_at")
    return {
        "metric": row["metric"],
        "batches_seen": row["batches_seen"],
        "batches_processed": row["batches_processed"],
        "batches_empty": row["batches_empty"],
        "batches_failed": row["batches_failed"],
        "records_received": row["records_received"],
        "records_accepted": row["records_accepted"],
        "records_inserted_new": row.get("records_inserted_new"),
        "records_deduped_existing": row.get("records_deduped_existing"),
        "storage_result_level": row.get("storage_result_level", "accepted_only"),
        "records_skipped": row["records_skipped"],
        "newest_receipt_at": row["newest_receipt_at"],
        "receipt_sample_window": _sample_window(row),
        "destination_row_count": row["destination_row_count"],
        "latest_destination_sample_time": destination_sample,
        "freshness_state": _freshness_state(
            receipt_sample_max=receipt_sample_max,
            latest_destination_sample=destination_sample,
        ),
    }


def _freshness_state(
    *,
    receipt_sample_max: Any,
    latest_destination_sample: Any,
) -> str:
    if latest_destination_sample is None:
        return "receipt_only" if receipt_sample_max is not None else "unknown"
    if receipt_sample_max is None:
        return "destination_only"
    if _compare_time_values(receipt_sample_max, latest_destination_sample) < 0:
        return "stale_payload"
    return "fresh"


def _compare_time_values(left: Any, right: Any) -> int:
    left_dt = _parse_time_value(left)
    right_dt = _parse_time_value(right)
    if left_dt is not None and right_dt is not None:
        return (left_dt > right_dt) - (left_dt < right_dt)
    return (str(left) > str(right)) - (str(left) < str(right))


def _parse_time_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text_value = str(value)
    if text_value.endswith("Z"):
        text_value = f"{text_value[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        return None


def _sum_optional(values: Any) -> int | None:
    materialized = [value for value in values if value is not None]
    if not materialized:
        return None
    return sum(materialized)


def _combined_storage_result_level(rows: list[dict[str, Any]]) -> str:
    if rows and all(row.get("storage_result_level") == "inserted_vs_existing" for row in rows):
        return "inserted_vs_existing"
    return "accepted_only"


async def sync_anomalies(session: AsyncSession, lookback_minutes: int = 15) -> dict[str, Any]:
    """Detect overlapping HealthSave sync runs from server-side receipts.

    A released client can accidentally start manual/background syncs together.
    The v1 ingest contract still accepts those batches, so this additive v2
    operator check flags the pattern before humans have to infer it from a noisy
    progress UI or raw logs.
    """

    result = await session.execute(
        text(
            """
            SELECT
                metric,
                count(DISTINCT sync_run_id) AS sync_runs,
                count(*) AS batches_seen,
                coalesce(sum(records_accepted), 0) AS records_accepted,
                min(received_at) AS first_seen_at,
                max(received_at) AS latest_seen_at
            FROM healthsave_sync_receipts
            WHERE sync_run_id IS NOT NULL
              AND received_at > now() - (:lookback_minutes * interval '1 minute')
            GROUP BY metric
            HAVING count(DISTINCT sync_run_id) > 1
            ORDER BY sync_runs DESC, batches_seen DESC, metric
            """
        ),
        {"lookback_minutes": lookback_minutes},
    )
    rows = [dict(row) for row in result.mappings().all()]
    anomalies = [
        {
            "type": "overlapping_sync_runs",
            "severity": "critical" if row["sync_runs"] >= 3 else "warning",
            "metric": row["metric"],
            "sync_runs": row["sync_runs"],
            "batches_seen": row["batches_seen"],
            "records_accepted": row["records_accepted"],
            "first_seen_at": row["first_seen_at"],
            "latest_seen_at": row["latest_seen_at"],
            "message": (
                f"Detected {row['sync_runs']} overlapping sync runs for "
                f"{row['metric']} in the last {lookback_minutes} minutes."
            ),
            "recommended_action": (
                "Force quit HealthSave, wait 1–2 minutes for queued uploads to drain, "
                "then run only one manual sync. Install a build with the sync-run guard "
                "before retrying full history sync."
            ),
        }
        for row in rows
    ]
    return {
        "status": "warning" if anomalies else "ok",
        "lookback_minutes": lookback_minutes,
        "summary": {
            "overlapping_metrics": len(anomalies),
            "max_concurrent_sync_runs": max(
                (anomaly["sync_runs"] for anomaly in anomalies), default=0
            ),
        },
        "anomalies": anomalies,
        # Additive: windows a source poll (Whoop, Amazfit, Polar, Google)
        # could not backfill and gave up on. Not part of "status", which stays
        # about overlapping phone syncs; a gap is history, not a live problem.
        "source_backfill_gaps": await _source_backfill_gaps(session),
    }


async def _source_backfill_gaps(session: AsyncSession) -> list[dict[str, Any]]:
    from storage.timescale.source_poll_cursors import list_unfilled_gaps

    return [
        {
            "type": "source_backfill_given_up",
            "severity": "warning",
            "provider": gap["provider"],
            "unfilled_from": gap["unfilled_gap_start"],
            "unfilled_to": gap["unfilled_gap_end"],
            "last_successful_poll_at": gap["last_success_at"],
            "message": (
                f"{gap['provider']} did not serve the data between the two times above, "
                "so the backfill was given up and that stretch is missing here."
            ),
            "recommended_action": (
                "If you need it, export that stretch from the vendor's own app and "
                "import it, or re-authorize the connection to try the backfill again."
            ),
        }
        for gap in await list_unfilled_gaps(session)
    ]


class TimescaleSyncReceiptRepository:
    """Timescale-backed :class:`storage.ports.SyncReceiptRepository`."""

    async def latest_sync_run(
        self, session: AsyncSession, owner_id: UUID | None = None
    ) -> dict[str, Any]:
        return await latest_sync_run(session, owner_id)

    async def sync_run(
        self, session: AsyncSession, sync_run_id: str, owner_id: UUID | None = None
    ) -> dict[str, Any]:
        return await sync_run(session, sync_run_id, owner_id)

    async def record_sync_run_summary(self, session: AsyncSession, **fields: Any) -> dict[str, Any]:
        return await record_sync_run_summary(session, **fields)

    async def sync_coverage(self, session: AsyncSession) -> dict[str, Any]:
        return await sync_coverage(session)

    async def sync_anomalies(
        self,
        session: AsyncSession,
        lookback_minutes: int = 15,
    ) -> dict[str, Any]:
        return await sync_anomalies(session, lookback_minutes)


default_repository = TimescaleSyncReceiptRepository()
