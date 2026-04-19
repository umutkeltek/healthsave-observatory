"""Tests for /api/insights route behavior."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from server.api.insights import insights_anomalies, insights_trends, insights_trigger  # noqa: E402
from server.models.insights import TriggerRequest  # noqa: E402


class _FakeEngine:
    def __init__(self, run_id: int | None):
        self.run_id = run_id
        self.calls = 0
        self.trend_calls = 0

    async def run_daily_briefing(self):
        self.calls += 1
        return self.run_id

    async def run_trend_analysis(self):
        self.trend_calls += 1
        return []


def _request(*, enabled: bool, run_id: int | None = 123):
    config = AnalysisConfig.model_validate({"analysis": {"daily_briefing": {"enabled": enabled}}})
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=_FakeEngine(run_id),
            )
        )
    )


@pytest.mark.asyncio
async def test_trigger_accepts_missing_body_as_daily_briefing_default():
    request = _request(enabled=True, run_id=123)

    response = await insights_trigger(request)

    assert response.status == "completed"
    assert response.run_type == "daily_briefing"
    assert response.run_id == 123
    assert request.app.state.analysis_engine.calls == 1


@pytest.mark.asyncio
async def test_trigger_rejects_daily_briefing_when_analysis_is_disabled():
    request = _request(enabled=False)

    with pytest.raises(Exception) as exc_info:
        await insights_trigger(request, TriggerRequest(type="daily_briefing"))

    assert getattr(exc_info.value, "status_code", None) == 409
    assert request.app.state.analysis_engine.calls == 0


@pytest.mark.asyncio
async def test_trigger_accepts_trend_analysis_when_enabled():
    config = AnalysisConfig.model_validate({"analysis": {"trend_analysis": {"enabled": True}}})
    engine = _FakeEngine(run_id=None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analysis_config=config,
                analysis_engine=engine,
            )
        )
    )

    response = await insights_trigger(request, TriggerRequest(type="trend_analysis"))

    assert response.status == "skipped"
    assert response.run_type == "trend_analysis"
    assert response.message == "0 trend findings persisted"
    assert engine.trend_calls == 1


# ──────────────────────────────────────────────────────────────
#  /api/insights/anomalies
# ──────────────────────────────────────────────────────────────


class _AnomalyRow(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row returned from analysis_findings."""


class _AnomalyResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _AnomalySession:
    """Captures the executed SQL + params so filter behaviour can be asserted."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        return _AnomalyResult(self._rows)


@pytest.mark.asyncio
async def test_insights_anomalies_returns_rows_ordered_desc_with_structured_data():
    now = datetime(2026, 4, 18, 14, 30, tzinfo=UTC)
    rows = [
        _AnomalyRow(
            id=11,
            metric="hrv",
            severity="alert",
            structured_data=json.dumps(
                {
                    "metric": "hrv",
                    "magnitude": -3.4,
                    "direction": "down",
                    "severity": "alert",
                    "detected_at": now.isoformat(),
                    "context": {"value": 18.0},
                }
            ),
            created_at=now,
        ),
        _AnomalyRow(
            id=9,
            metric="heart_rate",
            severity="watch",
            structured_data={
                "metric": "heart_rate",
                "magnitude": 2.7,
                "direction": "up",
                "severity": "watch",
            },
            created_at=now,
        ),
    ]
    session = _AnomalySession(rows)

    response = await insights_anomalies(since=None, severity=None, session=session)

    assert response.count == 2
    assert response.anomalies[0].metric == "hrv"
    assert response.anomalies[0].severity == "alert"
    assert response.anomalies[0].direction == "down"
    assert response.anomalies[0].magnitude == -3.4
    assert response.anomalies[1].metric == "heart_rate"

    sql, params = session.calls[0]
    assert "finding_type = 'anomaly'" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_insights_anomalies_empty_db_returns_empty_list_with_count_zero():
    session = _AnomalySession([])

    response = await insights_anomalies(since=None, severity=None, session=session)

    assert response.count == 0
    assert response.anomalies == []


@pytest.mark.asyncio
async def test_insights_anomalies_since_filter_passes_param_and_where_clause():
    session = _AnomalySession([])

    await insights_anomalies(since="2026-04-01T00:00:00Z", severity=None, session=session)

    sql, params = session.calls[0]
    assert "created_at >= :since" in sql
    assert params["since"] == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_insights_anomalies_severity_filter_accepts_comma_separated_values():
    session = _AnomalySession([])

    await insights_anomalies(since=None, severity="watch,alert", session=session)

    sql, params = session.calls[0]
    assert "severity IN (:severity_0, :severity_1)" in sql
    assert [params["severity_0"], params["severity_1"]] == ["alert", "watch"]


@pytest.mark.asyncio
async def test_insights_anomalies_severity_filter_ignores_unknown_values():
    session = _AnomalySession([])

    with pytest.raises(Exception) as exc_info:
        await insights_anomalies(since=None, severity="bogus", session=session)

    assert getattr(exc_info.value, "status_code", None) == 422
    assert session.calls == []


# ──────────────────────────────────────────────────────────────
#  /api/insights/trends
# ──────────────────────────────────────────────────────────────


class _TrendRow(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row returned from analysis_findings."""


class _TrendResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _TrendSession:
    def __init__(self, rows):
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        return _TrendResult(self._rows)


@pytest.mark.asyncio
async def test_insights_trends_returns_recent_trend_findings():
    rows = [
        _TrendRow(
            id=21,
            metric="heart_rate",
            structured_data=json.dumps(
                {
                    "metric": "heart_rate",
                    "slope": 0.42,
                    "direction": "up",
                    "period_days": 30,
                    "p_value": 0.004,
                    "confidence": "high",
                }
            ),
            created_at=datetime(2026, 4, 19, 9, 0, tzinfo=UTC),
        ),
        _TrendRow(
            id=22,
            metric="hrv",
            structured_data={
                "metric": "hrv",
                "slope": -0.9,
                "direction": "down",
                "period_days": 30,
                "p_value": 0.02,
                "confidence": "medium",
            },
            created_at=datetime(2026, 4, 19, 9, 0, tzinfo=UTC),
        ),
    ]
    session = _TrendSession(rows)

    response = await insights_trends(period=None, session=session)

    assert response.count == 2
    assert response.trends[0].metric == "heart_rate"
    assert response.trends[0].direction == "up"
    assert response.trends[0].slope == 0.42
    assert response.trends[1].metric == "hrv"

    sql, params = session.calls[0]
    assert "finding_type = 'trend'" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT" in sql
    assert params["limit"] == 200


@pytest.mark.asyncio
async def test_insights_trends_period_filter_accepts_day_suffix():
    session = _TrendSession([])

    response = await insights_trends(period="30d", session=session)

    assert response.count == 0
    sql, params = session.calls[0]
    assert "structured_data->>'period_days' = :period_days" in sql
    assert params["period_days"] == "30"


@pytest.mark.asyncio
async def test_insights_trends_rejects_invalid_period():
    session = _TrendSession([])

    with pytest.raises(Exception) as exc_info:
        await insights_trends(period="month", session=session)

    assert getattr(exc_info.value, "status_code", None) == 422
    assert session.calls == []
