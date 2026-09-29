"""Only active-slot races may be retried; retries must preserve the transaction."""

from unittest.mock import AsyncMock

import asyncpg
import pytest
from server.api.ingest import _is_transient_write_error
from sqlalchemy.exc import IntegrityError
from storage.timescale import measurements


def _unique_error(constraint: str) -> IntegrityError:
    original = asyncpg.UniqueViolationError("synthetic constraint conflict")
    original.constraint_name = constraint
    return IntegrityError("INSERT", {}, original)


def _session() -> tuple[AsyncMock, AsyncMock]:
    session = AsyncMock()
    savepoint = AsyncMock()
    session.begin_nested.return_value = savepoint
    return session, savepoint


SAMPLE = {
    "date": "2026-09-25T08:43:00Z",
    "qty": 72,
    "uuid": "b7d59aba-04af-4bf4-84be-4ab5576d55b8",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("constraint", ["uq_heart_rate", "_hyper_1_572_chunk_uq_heart_rate"])
async def test_active_slot_retry_is_bounded_and_exhaustion_is_transient(monkeypatch, constraint):
    writer = AsyncMock(side_effect=_unique_error(constraint))
    monkeypatch.setattr(measurements, "_execute_batch_insert_with_flags", writer)
    session, savepoint = _session()
    with pytest.raises(Exception) as raised:
        await measurements._ingest_dedicated(session, 24, "heart_rate", [SAMPLE])
    assert writer.await_count == 3
    assert savepoint.rollback.await_count == 3
    assert session.rollback.await_count == 0, "do not roll back the caller's canonical/audit work"
    assert _is_transient_write_error(raised.value), (
        "exhausted contention must not become permanent 422"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "constraint", ["uq_heart_rate_source_uuid", "uq_hrv", "other_uq_heart_rate"]
)
async def test_unrelated_integrity_failure_is_never_retried(monkeypatch, constraint):
    error = _unique_error(constraint)
    writer = AsyncMock(side_effect=error)
    monkeypatch.setattr(measurements, "_execute_batch_insert_with_flags", writer)
    session, _ = _session()
    with pytest.raises(IntegrityError) as raised:
        await measurements._ingest_dedicated(session, 24, "heart_rate", [SAMPLE])
    assert raised.value is error
    assert writer.await_count == 1
    assert not _is_transient_write_error(error)


@pytest.mark.asyncio
async def test_retry_reconciles_again_after_rolling_back_only_savepoint(monkeypatch):
    writer = AsyncMock(side_effect=[_unique_error("_hyper_1_572_chunk_uq_heart_rate"), [True]])
    supersede = AsyncMock()
    monkeypatch.setattr(measurements, "_execute_batch_insert_with_flags", writer)
    monkeypatch.setattr(measurements, "_supersede_revised_source_uuids", supersede)
    session, savepoint = _session()
    result = await measurements._ingest_dedicated(session, 24, "heart_rate", [SAMPLE])
    assert result.accepted == 1
    assert writer.await_count == supersede.await_count == 2
    assert savepoint.rollback.await_count == 1
    assert savepoint.commit.await_count == 1
    assert session.rollback.await_count == 0
