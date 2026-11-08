"""E2E: a stored batch's receipt names its sync run even when enrichment fails.

The batch route commits the data together with the receipt's frozen
response, then writes the run headers (sync run id, batch id, mode...) in a
separate best-effort step. When that step failed, the receipt kept no
``sync_run_id`` and ``GET /api/v2/sync/runs/latest`` never saw the run that
delivered it. One way it fails: a batch id another receipt already holds
(the per-owner batch-id index), as when a client re-sends a batch under a new
idempotency key.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
DATABASE_URL = os.getenv("E2E_DATABASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL or not DATABASE_URL,
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e",
    ),
]


def _batch(source: str, at: datetime) -> dict:
    return {
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [{"date": at.isoformat(), "qty": 61, "source": source}],
    }


def _headers(run_id: str, batch_id: str, key: str) -> dict[str, str]:
    headers = {
        "X-HealthSave-Sync-Run-ID": run_id,
        "X-HealthSave-Batch-ID": batch_id,
        "Idempotency-Key": key,
    }
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


@pytest.mark.asyncio
async def test_the_receipt_names_its_run_when_enrichment_fails() -> None:
    source = f"e2e run attribution {uuid4()}"
    batch_id = f"e2e-batch-{uuid4()}"
    first_run, second_run = f"e2e-run-{uuid4()}", f"e2e-run-{uuid4()}"
    second_key = f"e2e-key-{uuid4()}"
    at = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        first = await client.post(
            "/api/apple/batch",
            json=_batch(source, at),
            headers=_headers(first_run, batch_id, f"e2e-key-{uuid4()}"),
        )
        assert first.status_code in (200, 201, 202), first.text[:400]
        # Same batch id, new idempotency key: the enrichment upsert collides
        # with the first receipt's batch id and is rolled back.
        second = await client.post(
            "/api/apple/batch",
            json=_batch(source, at + timedelta(minutes=1)),
            headers=_headers(second_run, batch_id, second_key),
        )
        assert second.status_code in (200, 201, 202), second.text[:400]

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT status, sync_run_id FROM healthsave_sync_receipts WHERE idempotency_key = $1",
            second_key,
        )
    finally:
        await conn.close()

    assert row["status"] == "processed"
    assert row["sync_run_id"] == second_run
