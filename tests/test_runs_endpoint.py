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


# ──────────────────────────────────────────────────────────────
#  POST /api/insights/trigger writes a pipeline_runs row (Phase 4D)
# ──────────────────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

from analysis.config import AnalysisConfig  # noqa: E402
from compat_v1.models import TriggerRequest  # noqa: E402
from server.api.insights import insights_trigger  # noqa: E402


class _LedgerFakeSession:
    """FakeSession that returns a row id from claim_run and records
    every UPDATE so we can assert the trigger wrote the right marker."""

    def __init__(self, claim_id: int = 99) -> None:
        self.claim_id = claim_id
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "INSERT INTO pipeline_runs" in sql:
            return SimpleNamespace(first=lambda: SimpleNamespace(id=self.claim_id))
        return SimpleNamespace(first=lambda: None)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _LedgerFakeFactory:
    """Async context-manager factory like async_sessionmaker —
    returns a fresh _LedgerFakeSession that shares state via the
    factory's `sessions` list so tests can inspect every call."""

    def __init__(self, claim_id: int = 99) -> None:
        self.sessions: list[_LedgerFakeSession] = []
        self.claim_id = claim_id

    def __call__(self):
        s = _LedgerFakeSession(claim_id=self.claim_id)
        self.sessions.append(s)
        return s


class _OkEngine:
    async def run_daily_briefing(self) -> int:
        return 42


class _BoomEngine:
    async def run_daily_briefing(self) -> int:
        raise RuntimeError("engine exploded")


def _trigger_request(*, factory, engine):
    config = AnalysisConfig.model_validate({"analysis": {"daily_briefing": {"enabled": True}}})
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=engine,
                session_factory=factory,
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_writes_pipeline_run_on_success() -> None:
    """Phase 5G: ledger writes use ensure_terminal (INSERT … ON CONFLICT
    DO UPDATE) instead of bare UPDATE so the post-claim race window is
    closed. Test pins the new SQL shape + the status/job_kind/triggered_by
    params (which the ensure_terminal upsert needs in case the row
    didn't exist yet)."""
    factory = _LedgerFakeFactory(claim_id=42)
    request = _trigger_request(factory=factory, engine=_OkEngine())

    response = await insights_trigger(request, TriggerRequest(type="daily_briefing"))

    assert response.status == "completed"
    # Two sessions opened: claim, ensure_terminal(succeeded).
    assert len(factory.sessions) == 2
    sql_claim, params_claim = factory.sessions[0].calls[-1]
    assert "INSERT INTO pipeline_runs" in sql_claim
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in sql_claim
    assert params_claim["job_kind"] == "daily_briefing"
    assert params_claim["triggered_by"] == "api"
    sql_mark, params_mark = factory.sessions[1].calls[-1]
    assert "ON CONFLICT (idempotency_key) DO UPDATE" in sql_mark
    assert params_mark["status"] == "succeeded"
    assert params_mark["job_kind"] == "daily_briefing"
    assert params_mark["triggered_by"] == "api"
    # engine_run_id (42) gets coerced into the JSON result payload.
    assert '"engine_run_id": 42' in params_mark["result"]


@pytest.mark.asyncio
async def test_trigger_writes_pipeline_run_on_failure() -> None:
    factory = _LedgerFakeFactory(claim_id=7)
    request = _trigger_request(factory=factory, engine=_BoomEngine())

    with pytest.raises(RuntimeError, match="engine exploded"):
        await insights_trigger(request, TriggerRequest(type="daily_briefing"))

    # Two sessions: claim, ensure_terminal(failed).
    assert len(factory.sessions) == 2
    sql_mark, params_mark = factory.sessions[1].calls[-1]
    assert "ON CONFLICT (idempotency_key) DO UPDATE" in sql_mark
    assert params_mark["status"] == "failed"
    assert "engine exploded" in params_mark["error"]


@pytest.mark.asyncio
async def test_trigger_no_session_factory_degrades_gracefully() -> None:
    """When app.state.session_factory is missing, the trigger still runs
    and returns the same response — the ledger write is silently skipped."""

    config = AnalysisConfig.model_validate({"analysis": {"daily_briefing": {"enabled": True}}})
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_OkEngine(),
                # session_factory deliberately absent.
            )
        )
    )

    response = await insights_trigger(request, TriggerRequest(type="daily_briefing"))
    assert response.status == "completed"
    assert response.run_id == 42
