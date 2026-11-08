"""E2E: a failed attempt does not pin its idempotency key to its body.

A failed batch stores nothing and has no frozen response, but its receipt kept
the key bound to that attempt's payload hash. A later request with the same
key and a different body (the client re-encoded the batch) was refused with
409 ``idempotency_key_payload_mismatch`` on every retry. A completed key keeps
refusing a different body, as before.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


async def _record(session, *, owner, key, payload_hash, status) -> None:
    from storage.timescale.sync_receipts import record_sync_receipt

    await record_sync_receipt(
        session,
        owner_id=owner,
        sync_run_id=None,
        batch_id=None,
        idempotency_key=key,
        payload_hash=payload_hash,
        metric="heart_rate",
        batch_index=0,
        total_batches=1,
        sync_mode=None,
        anchor_present=None,
        lower_bound_reason=None,
        full_export=None,
        query_lower_bound_at=None,
        status=status,
        records_received=1,
        records_accepted=0 if status == "failed" else 1,
        records_skipped=0,
        sample_min_at=None,
        sample_max_at=None,
        raw_log_id=None,
        error_message="boom" if status == "failed" else None,
        response_payload=None if status == "failed" else {"status": "processed"},
    )


async def _claim(session, *, owner, key, payload_hash):
    from storage.timescale.sync_receipts import claim_receipt_idempotency

    return await claim_receipt_idempotency(
        session,
        owner_id=owner,
        idempotency_key=key,
        payload_hash=payload_hash,
        metric="heart_rate",
        batch_index=0,
        total_batches=1,
    )


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


@pytest.mark.asyncio
async def test_a_failed_key_can_be_claimed_by_a_different_body() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = _engine()
    owner, key = uuid4(), f"e2e-key-{uuid4()}"
    try:
        async with AsyncSession(engine) as session:
            await _record(session, owner=owner, key=key, payload_hash="sha256:a", status="failed")
            await session.commit()
        async with AsyncSession(engine) as session:
            # None: this request now owns the claim and will process the batch.
            assert await _claim(session, owner=owner, key=key, payload_hash="sha256:b") is None
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_completed_key_still_refuses_a_different_body() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.sync_receipts import ReceiptIdempotencyConflict

    engine = _engine()
    owner, key = uuid4(), f"e2e-key-{uuid4()}"
    try:
        async with AsyncSession(engine) as session:
            await _record(
                session, owner=owner, key=key, payload_hash="sha256:a", status="processed"
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(ReceiptIdempotencyConflict):
                await _claim(session, owner=owner, key=key, payload_hash="sha256:b")
            await session.rollback()
    finally:
        await engine.dispose()
