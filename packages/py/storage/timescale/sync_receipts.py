"""Timescale-backed HealthSave sync receipt queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_sync_receipt(
    session: AsyncSession,
    *,
    sync_run_id: str | None,
    batch_id: str | None,
    payload_hash: str | None,
    metric: str,
    batch_index: int,
    total_batches: int,
    status: str,
    records_accepted: int,
    records_skipped: int,
    raw_log_id: int | None,
    error_message: str | None = None,
) -> None:
    """Insert or update one HealthSave batch receipt.

    ``batch_id`` is unique when present so app retries update the receipt instead
    of making the support/operator view look like duplicate batches arrived.
    """

    await session.execute(
        text(
            """
            INSERT INTO healthsave_sync_receipts
                (
                    sync_run_id,
                    batch_id,
                    payload_hash,
                    metric,
                    batch_index,
                    total_batches,
                    status,
                    records_accepted,
                    records_skipped,
                    error_message,
                    raw_log_id,
                    source_endpoint,
                    completed_at
                )
            VALUES
                (
                    :sync_run_id,
                    :batch_id,
                    :payload_hash,
                    :metric,
                    :batch_index,
                    :total_batches,
                    :status,
                    :records_accepted,
                    :records_skipped,
                    :error_message,
                    :raw_log_id,
                    :source_endpoint,
                    now()
                )
            ON CONFLICT (batch_id) WHERE batch_id IS NOT NULL DO UPDATE SET
                sync_run_id = EXCLUDED.sync_run_id,
                payload_hash = EXCLUDED.payload_hash,
                metric = EXCLUDED.metric,
                batch_index = EXCLUDED.batch_index,
                total_batches = EXCLUDED.total_batches,
                status = EXCLUDED.status,
                records_accepted = EXCLUDED.records_accepted,
                records_skipped = EXCLUDED.records_skipped,
                error_message = EXCLUDED.error_message,
                raw_log_id = EXCLUDED.raw_log_id,
                completed_at = EXCLUDED.completed_at
            """
        ),
        {
            "sync_run_id": sync_run_id,
            "batch_id": batch_id,
            "payload_hash": payload_hash,
            "metric": metric,
            "batch_index": batch_index,
            "total_batches": total_batches,
            "status": status,
            "records_accepted": records_accepted,
            "records_skipped": records_skipped,
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
                coalesce(sum(records_accepted), 0) AS records_accepted,
                coalesce(sum(records_skipped), 0) AS records_skipped,
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
    return summary


async def sync_coverage(session: AsyncSession) -> dict[str, Any]:
    """Return metric-level receipt coverage from the Data Hub side."""

    result = await session.execute(
        text(
            """
            SELECT
                metric,
                count(*) AS batches_seen,
                count(*) FILTER (WHERE status = 'processed') AS batches_processed,
                count(*) FILTER (WHERE status = 'empty') AS batches_empty,
                count(*) FILTER (WHERE status = 'failed') AS batches_failed,
                coalesce(sum(records_accepted), 0) AS records_accepted,
                coalesce(sum(records_skipped), 0) AS records_skipped,
                max(coalesce(completed_at, received_at)) AS newest_receipt_at
            FROM healthsave_sync_receipts
            GROUP BY metric
            ORDER BY metric
            """
        )
    )
    rows = [dict(row) for row in result.mappings().all()]
    return {
        "status": "ok",
        "summary": {
            "metrics_seen": len(rows),
            "batches_seen": sum(row["batches_seen"] for row in rows),
            "records_accepted": sum(row["records_accepted"] for row in rows),
            "records_skipped": sum(row["records_skipped"] for row in rows),
        },
        "metrics": rows,
    }
