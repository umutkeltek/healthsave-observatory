"""Unit tests for the pipeline_runs ledger data layer.

Tests use a FakeSession that records SQL statements, mirroring the
pattern in tests/test_api_contract.py. Integration with a live
TimescaleDB is intentionally out of scope here — that fires when
the worker boots inside Compose.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from worker import runs
from worker.listener import _coerce_result, _idempotency_key


class _FakeResult:
    def __init__(self, row=None, rows: list | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Records SQL + params; returns canned results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.committed = False
        self.next_result: _FakeResult = _FakeResult()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        return self.next_result

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


def _last_call(session: _FakeSession) -> tuple[str, dict]:
    assert session.calls, "no SQL executed"
    return session.calls[-1]


# ---------------- runs.claim_run ----------------


@pytest.mark.asyncio
async def test_claim_run_returns_id_on_insert() -> None:
    session = _FakeSession()
    session.next_result = _FakeResult(row=type("R", (), {"id": 42})())

    rid = await runs.claim_run(
        session,
        job_kind="daily_briefing",
        idempotency_key="daily_briefing:2026-05-10",
        leased_by="worker:1",
    )

    assert rid == 42
    sql, params = _last_call(session)
    assert "INSERT INTO pipeline_runs" in sql
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in sql
    assert params["job_kind"] == "daily_briefing"
    assert params["idempotency_key"] == "daily_briefing:2026-05-10"
    assert params["leased_by"] == "worker:1"
    assert params["triggered_by"] == "scheduler"


@pytest.mark.asyncio
async def test_claim_run_returns_none_on_conflict() -> None:
    session = _FakeSession()
    session.next_result = _FakeResult(row=None)

    rid = await runs.claim_run(
        session,
        job_kind="daily_briefing",
        idempotency_key="daily_briefing:2026-05-10",
    )

    assert rid is None


# ---------------- runs.mark_succeeded ----------------


@pytest.mark.asyncio
async def test_mark_succeeded_updates_with_result_json() -> None:
    session = _FakeSession()
    await runs.mark_succeeded(session, run_id=7, result={"records": 12})

    sql, params = _last_call(session)
    assert "status = 'succeeded'" in sql
    assert params["run_id"] == 7
    assert params["result"] == '{"records": 12}'


@pytest.mark.asyncio
async def test_mark_succeeded_handles_none_result() -> None:
    session = _FakeSession()
    await runs.mark_succeeded(session, run_id=1)
    _, params = _last_call(session)
    assert params["result"] is None


# ---------------- runs.mark_failed ----------------


@pytest.mark.asyncio
async def test_mark_failed_truncates_long_error() -> None:
    session = _FakeSession()
    huge = "x" * 20000
    await runs.mark_failed(session, run_id=3, error=huge)

    sql, params = _last_call(session)
    assert "status = 'failed'" in sql
    assert params["run_id"] == 3
    assert len(params["error"]) == 8000


# ---------------- runs.mark_skipped ----------------


@pytest.mark.asyncio
async def test_mark_skipped_records_reason() -> None:
    session = _FakeSession()
    await runs.mark_skipped(session, run_id=5, reason="already done today")
    sql, params = _last_call(session)
    assert "status = 'skipped'" in sql
    assert params["reason"] == "already done today"


# ---------------- runs.fetch_recent ----------------


@pytest.mark.asyncio
async def test_fetch_recent_filters_by_job_kind() -> None:
    session = _FakeSession()
    session.next_result = _FakeResult(rows=[])

    await runs.fetch_recent(session, job_kind="anomaly_check", limit=50)

    sql, params = _last_call(session)
    assert "WHERE job_kind = :job_kind" in sql
    assert params["job_kind"] == "anomaly_check"
    assert params["limit"] == 50


@pytest.mark.asyncio
async def test_fetch_recent_decodes_string_result_payload() -> None:
    session = _FakeSession()
    row = type(
        "R",
        (),
        {
            "id": 9,
            "job_kind": "daily_briefing",
            "idempotency_key": "daily_briefing:2026-05-10",
            "status": "succeeded",
            "started_at": datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 5, 10, 6, 1, tzinfo=UTC),
            "result": '{"records": 12}',  # string form, like raw JSON column
            "error": None,
            "attempt": 1,
            "triggered_by": "scheduler",
        },
    )()
    session.next_result = _FakeResult(rows=[row])

    out = await runs.fetch_recent(session)
    assert len(out) == 1
    assert out[0].id == 9
    assert out[0].result == {"records": 12}


# ---------------- listener helpers ----------------


def test_idempotency_key_handles_list_and_datetime() -> None:
    dt = datetime(2026, 5, 10, 6, 0, tzinfo=UTC)
    assert _idempotency_key("daily_briefing", dt) == f"daily_briefing:{dt.isoformat()}"
    # APScheduler coalesce produces a list of scheduled run times
    assert _idempotency_key("daily_briefing", [dt]) == f"daily_briefing:{dt.isoformat()}"
    assert _idempotency_key("daily_briefing", []) == "daily_briefing:now"
    assert _idempotency_key("daily_briefing", None) == "daily_briefing:now"


def test_coerce_result_shapes() -> None:
    assert _coerce_result(None) is None
    assert _coerce_result(42) == {"value": 42}
    assert _coerce_result({"records": 12}) == {"records": 12}
    coerced = _coerce_result(object())
    assert coerced is not None
    assert "repr" in coerced
