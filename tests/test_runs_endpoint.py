"""Tests for GET /api/insights/runs (Phase 4C).

Verifies the route reads via runtime.runs.fetch_recent and shapes
the response into RunsListResponse. Uses the same FakeSession
pattern as the rest of the suite so no live DB is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from server.api.insights import insights_runs


class _Row:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        return _FakeResult(self.rows)


def _row(**kw):
    """Build a row with the columns fetch_recent SELECTs."""
    base = {
        "id": 1,
        "job_kind": "daily_briefing",
        "idempotency_key": "daily_briefing:2026-05-10T06:00:00",
        "status": "succeeded",
        "started_at": datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 5, 10, 6, 1, tzinfo=UTC),
        "result": '{"records": 12}',
        "error": None,
        "attempt": 1,
        "triggered_by": "scheduler",
    }
    base.update(kw)
    return _Row(**base)


@pytest.mark.asyncio
async def test_runs_returns_recent_rows() -> None:
    session = _FakeSession([_row(id=1), _row(id=2, status="failed", error="boom")])

    response = await insights_runs(job_kind=None, limit=100, session=session)

    assert response.count == 2
    assert response.runs[0].id == 1
    assert response.runs[0].status == "succeeded"
    assert response.runs[1].id == 2
    assert response.runs[1].status == "failed"
    assert response.runs[1].error == "boom"


@pytest.mark.asyncio
async def test_runs_filters_by_job_kind() -> None:
    session = _FakeSession([_row(job_kind="anomaly_check")])

    await insights_runs(job_kind="anomaly_check", limit=50, session=session)

    sql, params = session.calls[-1]
    assert "WHERE job_kind = :job_kind" in sql
    assert params["job_kind"] == "anomaly_check"
    assert params["limit"] == 50


@pytest.mark.asyncio
async def test_runs_empty_response_is_well_formed() -> None:
    session = _FakeSession([])
    response = await insights_runs(job_kind=None, limit=100, session=session)
    assert response.count == 0
    assert response.runs == []
