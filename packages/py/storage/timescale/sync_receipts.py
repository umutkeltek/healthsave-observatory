"""Timescale-backed HealthSave sync receipt queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from normalization.mappers import DAILY_ACTIVITY_QUANTITY_FIELDS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


def _destination_union_sql() -> str:
    """Build the ``destination_union`` CTE body.

    The ``daily_activity`` quantity rollups are derived from the source-of-truth
    mapper (``DAILY_ACTIVITY_QUANTITY_FIELDS``) so a newly added field can never
    silently reopen the GH#14 resend loop — the drift-guard contract test pins
    this set against the ingest routing.
    """

    fragments = [
        # Dedicated tables that store real per-sample timestamps.
        "SELECT 'heart_rate' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM heart_rate",
        "SELECT 'heart_rate_variability' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM hrv",
        "SELECT 'oxygen_saturation' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM blood_oxygen",
        # body_temperature + wrist_temperature share one table with no in-row
        # type discriminator (the writer never sets measurement_type), so both
        # report its max(time).
        "SELECT 'body_temperature' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM body_temperature",
        "SELECT 'wrist_temperature' AS metric, count(*) AS row_count, "
        "max(time) AS latest_sample_at FROM body_temperature",
        "SELECT 'sleep_analysis' AS metric, count(*) AS row_count, "
        "max(start_time) AS latest_sample_at FROM sleep_sessions",
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
    return "\n                UNION ALL\n                ".join(fragments)


def _sync_coverage_query() -> str:
    """Assemble the full metric-coverage SQL.

    The ``destination_union`` body and the date-rollup metric list are
    interpolated from trusted internal constants (never client input).
    """

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
                    min(sample_min_at) AS receipt_sample_min_at,
                    max(sample_max_at) AS receipt_sample_max_at
                FROM healthsave_sync_receipts
                GROUP BY metric
            ),
            destination_union AS (
                {_destination_union_sql()}
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


async def assert_receipt_idempotency(
    session: AsyncSession,
    *,
    idempotency_key: str | None,
    payload_hash: str | None,
) -> None:
    """Fail before ingest when a POST retry key points at a new payload."""

    if not idempotency_key or not payload_hash:
        return

    result = await session.execute(
        text(
            """
            SELECT payload_hash
            FROM healthsave_sync_receipts
            WHERE idempotency_key = :idempotency_key
            LIMIT 1
            """
        ),
        {"idempotency_key": idempotency_key},
    )
    row = result.mappings().first()
    if row is None:
        return

    existing_hash = row.get("payload_hash") if hasattr(row, "get") else row["payload_hash"]
    if existing_hash and existing_hash != payload_hash:
        raise ReceiptIdempotencyConflict(
            "This idempotency key was already received with a different payload hash."
        )


async def record_sync_receipt(
    session: AsyncSession,
    *,
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
) -> None:
    """Insert or update one HealthSave batch receipt.

    ``batch_id`` is unique when present so app retries update the receipt instead
    of making the support/operator view look like duplicate batches arrived.

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
                    completed_at
                )
            VALUES
                (
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
                    now()
                )
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO UPDATE SET
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
                completed_at = EXCLUDED.completed_at
            """
        ),
        {
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
        },
    )


async def latest_sync_run(session: AsyncSession) -> dict[str, Any]:
    """Summarize the most recently observed HealthSave sync run."""

    result = await session.execute(
        text(
            """
            SELECT sync_run_id
            FROM healthsave_sync_receipts
            WHERE sync_run_id IS NOT NULL
            ORDER BY received_at DESC, id DESC
            LIMIT 1
            """
        )
    )
    row = result.mappings().first()
    if row is None:
        return {"status": "empty", "message": "No HealthSave sync receipts recorded yet."}

    sync_run_id = row["sync_run_id"]
    summary_result = await session.execute(
        text(
            """
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
            WHERE sync_run_id = :sync_run_id
            GROUP BY sync_run_id
            """
        ),
        {"sync_run_id": sync_run_id},
    )
    summary = dict(summary_result.mappings().first())
    summary["status"] = "ok"
    summary["sample_window"] = _sample_window(summary)
    summary["latest_sample_time"] = summary["sample_max_at"]
    return summary


async def sync_run(session: AsyncSession, sync_run_id: str) -> dict[str, Any]:
    """Return a receipt-level summary for one HealthSave sync run.

    This is a delivery receipt summary: it proves Data Hub saw and accepted
    batches for the run. It does not claim manifest-level sample verification.
    """

    result = await session.execute(
        text(
            """
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
            WHERE sync_run_id = :sync_run_id
            GROUP BY metric
            ORDER BY metric
            """
        ),
        {"sync_run_id": sync_run_id},
    )
    rows = [dict(row) for row in result.mappings().all()]
    if not rows:
        return {
            "status": "empty",
            "sync_run_id": sync_run_id,
            "message": "No HealthSave sync receipts recorded for this run.",
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
        "verification_level": "delivery_receipt",
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


async def sync_coverage(session: AsyncSession) -> dict[str, Any]:
    """Return metric-level receipt and destination sample coverage."""

    result = await session.execute(text(_sync_coverage_query()))
    rows = [_format_coverage_row(dict(row)) for row in result.mappings().all()]
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
    }


class TimescaleSyncReceiptRepository:
    """Timescale-backed :class:`storage.ports.SyncReceiptRepository`."""

    async def latest_sync_run(self, session: AsyncSession) -> dict[str, Any]:
        return await latest_sync_run(session)

    async def sync_run(self, session: AsyncSession, sync_run_id: str) -> dict[str, Any]:
        return await sync_run(session, sync_run_id)

    async def sync_coverage(self, session: AsyncSession) -> dict[str, Any]:
        return await sync_coverage(session)

    async def sync_anomalies(
        self,
        session: AsyncSession,
        lookback_minutes: int = 15,
    ) -> dict[str, Any]:
        return await sync_anomalies(session, lookback_minutes)


default_repository = TimescaleSyncReceiptRepository()
