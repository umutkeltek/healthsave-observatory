"""Tests for the additive /api/v2/insights/* surface.

Mirrors the v1 insights route tests' FakeSession discipline — no live DB,
AsyncMock engine. Covers the correlations read (mapping + period filter +
validation) and the on-demand trigger (enabled / disabled / unknown type).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from server.api.v2_insights import (  # noqa: E402
    TriggerBody,
    latest_narratives,
    list_correlations,
    list_findings,
    trigger,
)


class _Row(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row from analysis_findings."""


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _Session:
    """Fake AsyncSession. ``run_rows`` feeds the ``analysis_runs`` read that
    /latest now issues alongside the narratives read; other queries get ``rows``."""

    def __init__(self, rows, run_rows=()):
        self._rows = list(rows)
        self._run_rows = list(run_rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "FROM analysis_runs" in sql:
            return _Result(self._run_rows)
        return _Result(self._rows)


# ──────────────────────────────────────────────────────────────
#  GET /api/v2/insights/correlations
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_correlations_maps_structured_data_newest_first():
    rows = [
        _Row(
            id=31,
            metric="vital.hrv_sdnn~vital.resting_heart_rate",
            structured_data=json.dumps(
                {
                    "metric_a": "vital.hrv_sdnn",
                    "metric_b": "vital.resting_heart_rate",
                    "coefficient": -0.82,
                    "method": "spearman",
                    "period_days": 90,
                    "p_value": 0.0001,
                }
            ),
            created_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
        ),
    ]
    session = _Session(rows)

    result = await list_correlations(period=None, session=session)

    assert result["count"] == 1
    c = result["correlations"][0]
    assert c["metric_a"] == "vital.hrv_sdnn"
    assert c["metric_b"] == "vital.resting_heart_rate"
    assert c["coefficient"] == -0.82
    assert c["method"] == "spearman"
    assert c["created_at"] == "2026-04-19T10:00:00+00:00"

    sql, params = session.calls[0]
    assert "finding_type = 'correlation'" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params["limit"] == 200


@pytest.mark.asyncio
async def test_list_correlations_period_filter_passes_param():
    session = _Session([])
    result = await list_correlations(period="90d", session=session)
    assert result == {"correlations": [], "count": 0}
    sql, params = session.calls[0]
    assert "structured_data->>'period_days' = :period_days" in sql
    assert params["period_days"] == "90"


@pytest.mark.asyncio
async def test_list_correlations_rejects_invalid_period():
    session = _Session([])
    with pytest.raises(Exception) as exc_info:
        await list_correlations(period="month", session=session)
    assert getattr(exc_info.value, "status_code", None) == 422
    assert session.calls == []


# ──────────────────────────────────────────────────────────────
#  GET /api/v2/insights/latest
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_latest_narratives_shapes_daily_and_weekly():
    rows = [
        _Row(
            insight_type="daily_briefing",
            narrative="Resting HR steady; HRV up 8%.",
            created_at=datetime(2026, 5, 1, 7, 0, tzinfo=UTC),
        ),
        _Row(
            insight_type="weekly_summary",
            narrative="A strong recovery week overall.",
            created_at=datetime(2026, 4, 28, 8, 0, tzinfo=UTC),
        ),
    ]
    session = _Session(rows)

    result = await latest_narratives(session=session)

    assert result["daily_briefing"]["narrative"] == "Resting HR steady; HRV up 8%."
    assert result["daily_briefing"]["created_at"] == "2026-05-01T07:00:00+00:00"
    assert result["weekly_summary"]["insight_type"] == "weekly_summary"


@pytest.mark.asyncio
async def test_latest_narratives_missing_types_are_null():
    session = _Session([])
    result = await latest_narratives(session=session)
    assert result == {
        "daily_briefing": None,
        "weekly_summary": None,
        "runs": {"daily_briefing": None, "weekly_summary": None},
    }


@pytest.mark.asyncio
async def test_latest_surfaces_failed_run_status():
    """A failed narrator attempt is visible even when no narrative exists —
    the card must be able to say "last attempt failed", not "no briefing yet"."""
    run_rows = [
        _Row(
            run_type="weekly_summary",
            status="failed",
            error_message="all 2 narrator candidate(s) failed: deepseek/deepseek-chat: timeout",
            started_at=datetime(2026, 6, 9, 6, 0, tzinfo=UTC),
            completed_at=datetime(2026, 6, 9, 6, 1, tzinfo=UTC),
            llm_provider=None,
        ),
    ]
    session = _Session([], run_rows=run_rows)

    result = await latest_narratives(session=session)

    assert result["weekly_summary"] is None
    run = result["runs"]["weekly_summary"]
    assert run["status"] == "failed"
    assert "timeout" in run["error"]
    assert run["at"] == "2026-06-09T06:00:00+00:00"
    assert run["completed_at"] == "2026-06-09T06:01:00+00:00"
    assert result["runs"]["daily_briefing"] is None

    runs_sql = next(sql for sql, _ in session.calls if "FROM analysis_runs" in sql)
    assert "DISTINCT ON (run_type)" in runs_sql
    assert "ORDER BY run_type, started_at DESC" in runs_sql


@pytest.mark.asyncio
async def test_latest_surfaces_completed_run_with_provider():
    run_rows = [
        _Row(
            run_type="daily_briefing",
            status="completed",
            error_message=None,
            started_at=datetime(2026, 6, 10, 7, 0, tzinfo=UTC),
            completed_at=datetime(2026, 6, 10, 7, 2, tzinfo=UTC),
            llm_provider="deepseek/deepseek-chat",
        ),
    ]
    session = _Session([], run_rows=run_rows)

    result = await latest_narratives(session=session)

    run = result["runs"]["daily_briefing"]
    assert run["status"] == "completed"
    assert run["error"] is None
    assert run["provider"] == "deepseek/deepseek-chat"


# ──────────────────────────────────────────────────────────────
#  GET /api/v2/insights/findings
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_findings_maps_rows_with_type_and_structured_data():
    rows = [
        _Row(
            id=7,
            finding_type="anomaly",
            metric="vital.hrv_sdnn",
            severity="alert",
            structured_data={"magnitude": 2.4, "direction": "down"},
            created_at=datetime(2026, 5, 2, 6, 0, tzinfo=UTC),
        ),
    ]
    session = _Session(rows)

    result = await list_findings(finding_type=None, session=session)

    assert result["count"] == 1
    finding = result["findings"][0]
    assert finding["finding_type"] == "anomaly"
    assert finding["metric"] == "vital.hrv_sdnn"
    assert finding["severity"] == "alert"
    assert finding["structured_data"]["direction"] == "down"
    assert finding["created_at"] == "2026-05-02T06:00:00+00:00"

    sql, params = session.calls[0]
    assert "FROM analysis_findings" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params["limit"] == 200
    assert "finding_type = :finding_type" not in sql  # no filter → no predicate


@pytest.mark.asyncio
async def test_list_findings_type_filter_passes_predicate():
    session = _Session([])
    result = await list_findings(finding_type="trend", session=session)
    assert result == {"findings": [], "count": 0}
    sql, params = session.calls[0]
    assert "finding_type = :finding_type" in sql
    assert params["finding_type"] == "trend"


@pytest.mark.asyncio
async def test_list_findings_rejects_unknown_type():
    session = _Session([])
    with pytest.raises(Exception) as exc_info:
        await list_findings(finding_type="bogus", session=session)
    assert getattr(exc_info.value, "status_code", None) == 422
    assert session.calls == []


# ──────────────────────────────────────────────────────────────
#  POST /api/v2/insights/trigger
# ──────────────────────────────────────────────────────────────


class _FakeEngine:
    def __init__(self, findings):
        self._findings = findings
        self.calls = 0

    async def run_correlation_analysis(self):
        self.calls += 1
        return self._findings


def _request(*, enabled: bool, findings: list | None = None):
    config = AnalysisConfig.model_validate(
        {"analysis": {"correlation_analysis": {"enabled": enabled}}}
    )
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_FakeEngine(findings or []),
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_runs_engine_when_enabled():
    request = _request(enabled=True, findings=[object(), object()])
    result = await trigger(request, TriggerBody(type="correlation_analysis"))
    assert result["status"] == "completed"
    assert result["run_type"] == "correlation_analysis"
    assert result["count"] == 2
    assert request.app.state.analysis_engine.calls == 1


@pytest.mark.asyncio
async def test_trigger_reports_skipped_when_no_findings():
    request = _request(enabled=True, findings=[])
    result = await trigger(request, TriggerBody())
    assert result["status"] == "skipped"
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_trigger_409_when_disabled():
    request = _request(enabled=False)
    with pytest.raises(Exception) as exc_info:
        await trigger(request, TriggerBody(type="correlation_analysis"))
    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.calls == 0


@pytest.mark.asyncio
async def test_trigger_400_for_unknown_type():
    request = _request(enabled=True)
    with pytest.raises(Exception) as exc_info:
        await trigger(request, TriggerBody(type="zen_garden_analysis"))
    assert getattr(exc_info.value, "status_code", None) == 400


class _FakeRecoveryEngine:
    def __init__(self, run_id):
        self._run_id = run_id
        self.calls = 0

    async def run_recovery_check(self):
        self.calls += 1
        return self._run_id


def _recovery_request(*, enabled: bool, run_id: int | None = 7):
    config = AnalysisConfig.model_validate({"analysis": {"recovery": {"enabled": enabled}}})
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_FakeRecoveryEngine(run_id),
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_recovery_check_runs_engine_when_enabled():
    request = _recovery_request(enabled=True, run_id=42)
    result = await trigger(request, TriggerBody(type="recovery_check"))
    assert result["status"] == "completed"
    assert result["run_type"] == "recovery_check"
    assert result["run_id"] == 42
    assert request.app.state.analysis_engine.calls == 1


@pytest.mark.asyncio
async def test_trigger_recovery_check_reports_skipped_when_no_signal():
    request = _recovery_request(enabled=True, run_id=None)
    result = await trigger(request, TriggerBody(type="recovery_check"))
    assert result["status"] == "skipped"
    assert result["run_id"] is None


@pytest.mark.asyncio
async def test_trigger_recovery_check_409_when_disabled():
    request = _recovery_request(enabled=False)
    with pytest.raises(Exception) as exc_info:
        await trigger(request, TriggerBody(type="recovery_check"))
    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.calls == 0


class _FakeBriefingEngine:
    def __init__(self, run_id):
        self._run_id = run_id
        self.calls = 0
        self.weekly_calls = 0

    async def run_daily_briefing(self):
        self.calls += 1
        return self._run_id

    async def run_weekly_summary(self):
        self.weekly_calls += 1
        return self._run_id


def _briefing_request(*, enabled: bool, run_id: int | None = 11, job: str = "daily_briefing"):
    config = AnalysisConfig.model_validate({"analysis": {job: {"enabled": enabled}}})
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_FakeBriefingEngine(run_id),
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_daily_briefing_runs_engine_when_enabled():
    request = _briefing_request(enabled=True, run_id=11)
    result = await trigger(request, TriggerBody(type="daily_briefing"))
    assert result["status"] == "completed"
    assert result["run_type"] == "daily_briefing"
    assert result["run_id"] == 11
    assert request.app.state.analysis_engine.calls == 1


@pytest.mark.asyncio
async def test_trigger_daily_briefing_reports_skipped_when_no_data():
    request = _briefing_request(enabled=True, run_id=None)
    result = await trigger(request, TriggerBody(type="daily_briefing"))
    assert result["status"] == "skipped"
    assert result["run_id"] is None


@pytest.mark.asyncio
async def test_trigger_daily_briefing_409_when_disabled():
    request = _briefing_request(enabled=False)
    with pytest.raises(Exception) as exc_info:
        await trigger(request, TriggerBody(type="daily_briefing"))
    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.calls == 0


@pytest.mark.asyncio
async def test_trigger_weekly_summary_runs_engine_when_enabled():
    request = _briefing_request(enabled=True, run_id=23, job="weekly_summary")
    result = await trigger(request, TriggerBody(type="weekly_summary"))
    assert result["status"] == "completed"
    assert result["run_type"] == "weekly_summary"
    assert result["run_id"] == 23
    assert request.app.state.analysis_engine.weekly_calls == 1
    assert request.app.state.analysis_engine.calls == 0  # daily untouched


@pytest.mark.asyncio
async def test_trigger_weekly_summary_409_when_disabled():
    request = _briefing_request(enabled=False, job="weekly_summary")
    with pytest.raises(Exception) as exc_info:
        await trigger(request, TriggerBody(type="weekly_summary"))
    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.weekly_calls == 0
