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
    def __init__(self, rows):
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
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
    assert result == {"daily_briefing": None, "weekly_summary": None}


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
        await trigger(request, TriggerBody(type="weekly_summary"))
    assert getattr(exc_info.value, "status_code", None) == 400
