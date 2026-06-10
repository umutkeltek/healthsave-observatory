"""Unit tests for :class:`analysis.engine.AnalysisEngine.run_daily_briefing`.

Extends the Phase 1 ``FakeSession`` discipline: no live DB, async mock
stands in for the LLM client. Covers success, empty-summary skip, and
LLM-failure re-raise paths.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from analysis.engine import AnalysisEngine  # noqa: E402
from analysis.llm.client import InsightResult, LLMUnavailableError  # noqa: E402
from analysis.types import Anomaly, Correlation, PeriodSummary, Trend  # noqa: E402


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = list(rows) if rows is not None else ([] if row is None else [row])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return list(self._rows)


class _FakeSession:
    """Async session stub recording every SQL statement.

    ``run_queue`` supplies the ``RETURNING id`` rows (first call: run_id,
    second call: finding_id). Other ``execute`` calls return an empty
    ``_Result`` - the engine only reads rows from the INSERT...RETURNING
    statements.
    """

    def __init__(self, run_queue: list[int], select_queue: list[list[_Row]] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.committed = False
        self._queue = list(run_queue)
        self._select_queue = list(select_queue or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if sql.startswith("SELECT") and self._select_queue:
            rows = self._select_queue.pop(0)
            return _Result(row=rows[0] if rows else None, rows=rows)
        if "RETURNING id" in sql and self._queue:
            return _Result(_Row(id=self._queue.pop(0)))
        return _Result()

    async def commit(self):
        self.committed = True

    def all_insert_params_for(self, table_name: str) -> list[dict]:
        needle = f"INSERT INTO {table_name}"
        return [params for sql, params in self.calls if needle in sql]

    def all_update_statements(self) -> list[tuple[str, dict]]:
        return [(sql, params) for sql, params in self.calls if sql.startswith("UPDATE")]


def _make_engine(session, aggregator_return, llm_mock):
    """Build an AnalysisEngine wired to the supplied fakes."""

    def factory():
        return session

    engine = AnalysisEngine(factory, llm_mock, AnalysisConfig())
    engine.aggregator.summarize_period = AsyncMock(return_value=aggregator_return)
    return engine


def _make_plain_engine(session, config=None):
    def factory():
        return session

    return AnalysisEngine(factory, AsyncMock(), config or AnalysisConfig())


@pytest.mark.asyncio
async def test_run_daily_briefing_success_writes_run_finding_and_insight():
    session = _FakeSession(run_queue=[101, 202])  # run_id=101, finding_id=202
    summary = PeriodSummary(
        period="daily",
        metrics={
            "heart_rate": {
                "avg_bpm": 65.0,
                "min_bpm": 55,
                "max_bpm": 120,
                "sample_count": 24,
                "baseline_avg_bpm": 62.0,
                "delta_pct_vs_baseline": 4.84,
            }
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Great morning. Not medical advice.",
        tokens_in=42,
        tokens_out=77,
        model="ollama/llama3.1:8b",
        insight_type="daily_briefing",
    )

    engine = _make_engine(session, summary, llm_mock)
    run_id = await engine.run_daily_briefing()

    assert run_id == 101
    assert session.committed is True
    # Run row was inserted and later updated to 'completed'
    assert len(session.all_insert_params_for("analysis_runs")) == 1
    # Finding row inserted once
    finding_inserts = session.all_insert_params_for("analysis_findings")
    assert len(finding_inserts) == 1
    assert finding_inserts[0]["metric"] == "heart_rate"
    assert finding_inserts[0]["severity"] == "info"
    # Insight row inserted once with findings_used pointing at finding_id 202
    insight_inserts = session.all_insert_params_for("analysis_insights")
    assert len(insight_inserts) == 1
    assert insight_inserts[0]["findings_used"] == [202]
    assert insight_inserts[0]["insight_type"] == "daily_briefing"
    # Final UPDATE to analysis_runs is the 'completed' transition
    updates = session.all_update_statements()
    assert any(
        "status = 'completed'" in sql and params.get("tokens_in") == 42 for sql, params in updates
    )
    llm_mock.generate_insight.assert_awaited_once()
    # Primary served → no failover audit event
    assert session.all_insert_params_for("intelligence_audit_events") == []


@pytest.mark.asyncio
async def test_run_daily_briefing_persists_failover_audit_event():
    """A brief served by a fallback leaves a narrator_failover audit event
    so /api/v2/receipts shows the provider switch (silent-failure review)."""
    from analysis.llm.client import FailoverAttempt

    session = _FakeSession(run_queue=[101, 202])
    summary = PeriodSummary(
        period="daily",
        metrics={"heart_rate": {"avg_bpm": 65.0, "sample_count": 24}},
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Fallback narrative. Not medical advice.",
        tokens_in=10,
        tokens_out=20,
        model="openrouter/gemini-2.5-flash-lite",
        insight_type="daily_briefing",
        failovers=[FailoverAttempt(candidate="deepseek/deepseek-chat", error="timeout after 60s")],
    )

    engine = _make_engine(session, summary, llm_mock)
    run_id = await engine.run_daily_briefing()

    assert run_id == 101
    audit_inserts = session.all_insert_params_for("intelligence_audit_events")
    assert len(audit_inserts) == 1
    assert audit_inserts[0]["event_type"] == "narrator_failover"
    metadata = json.loads(audit_inserts[0]["metadata"])
    assert metadata["insight_type"] == "daily_briefing"
    assert metadata["served_by"] == "openrouter/gemini-2.5-flash-lite"
    assert metadata["failed_candidates"] == [
        {"candidate": "deepseek/deepseek-chat", "error": "timeout after 60s"}
    ]


@pytest.mark.asyncio
async def test_failover_audit_write_failure_does_not_fail_the_briefing(monkeypatch):
    """The audit write is best-effort: a missing intelligence_audit_events
    table (pre-migration-017 DB) must not kill a brief that already succeeded."""
    from analysis.llm.client import FailoverAttempt
    from storage.timescale import intelligence as intelligence_module

    session = _FakeSession(run_queue=[101, 202])
    summary = PeriodSummary(
        period="daily",
        metrics={"heart_rate": {"avg_bpm": 65.0, "sample_count": 24}},
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Fallback narrative. Not medical advice.",
        tokens_in=10,
        tokens_out=20,
        model="ollama/llama3.2:3b",
        insight_type="daily_briefing",
        failovers=[FailoverAttempt(candidate="deepseek/deepseek-chat", error="boom")],
    )
    monkeypatch.setattr(
        intelligence_module.default_repository,
        "record_audit",
        AsyncMock(side_effect=RuntimeError("relation does not exist")),
    )

    engine = _make_engine(session, summary, llm_mock)
    run_id = await engine.run_daily_briefing()

    assert run_id == 101
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_daily_briefing_skips_when_summary_is_empty():
    session = _FakeSession(run_queue=[303])
    empty_summary = PeriodSummary(period="daily", metrics={})
    llm_mock = AsyncMock()

    engine = _make_engine(session, empty_summary, llm_mock)
    run_id = await engine.run_daily_briefing()

    # Skipped runs return None so the trigger route can distinguish
    # "completed with insight" from "nothing to narrate".
    assert run_id is None
    # LLM never called on empty-data path
    llm_mock.generate_insight.assert_not_awaited()
    # No finding row, no insight row
    assert session.all_insert_params_for("analysis_findings") == []
    assert session.all_insert_params_for("analysis_insights") == []
    # Status updated to 'skipped' (run row 303 is still persisted for audit)
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)
    assert any(params.get("id") == 303 for _, params in updates)
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_daily_briefing_persists_anomaly_findings_and_includes_them_in_prompt():
    """Phase 2: detector-supplied anomalies become finding rows + prompt lines."""
    # run_id=900, hr_finding_id=901, hrv_finding_id=902, anomaly_finding_id=903.
    session = _FakeSession(run_queue=[900, 901, 902, 903])
    summary = PeriodSummary(
        period="daily",
        metrics={
            "heart_rate": {
                "avg_bpm": 72.0,
                "min_bpm": 58,
                "max_bpm": 140,
                "sample_count": 24,
                "baseline_avg_bpm": 65.0,
                "delta_pct_vs_baseline": 10.77,
            },
            "hrv": {
                "avg_ms": 38.0,
                "min_ms": 20,
                "max_ms": 62,
                "sample_count": 18,
                "baseline_avg_ms": 52.0,
                "delta_pct_vs_baseline": -26.92,
            },
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Your HRV dipped yesterday. Not medical advice.",
        tokens_in=50,
        tokens_out=80,
        model="ollama/llama3.1:8b",
        insight_type="daily_briefing",
    )

    engine = _make_engine(session, summary, llm_mock)
    engine.config.analysis.anomaly_detection.enabled = True
    engine.anomaly_detector.detect = AsyncMock(
        return_value=[Anomaly(metric="hrv", magnitude=-3.1, direction="down", severity="alert")]
    )

    run_id = await engine.run_daily_briefing()

    assert run_id == 900
    # Three finding rows: HR summary + HRV summary + HRV anomaly
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 3
    assert findings[0]["finding_type"] == "summary"
    assert findings[0]["metric"] == "heart_rate"
    assert findings[1]["finding_type"] == "summary"
    assert findings[1]["metric"] == "hrv"
    assert findings[2]["finding_type"] == "anomaly"
    assert findings[2]["metric"] == "hrv"
    assert findings[2]["severity"] == "alert"

    # Insight references all summary/anomaly finding ids.
    insight_inserts = session.all_insert_params_for("analysis_insights")
    assert insight_inserts[0]["findings_used"] == [901, 902, 903]

    # Anomalies were formatted into the LLM prompt.
    prompt_arg = llm_mock.generate_insight.await_args.args[0]
    assert "hrv: down deviation" in prompt_arg
    assert "severity=alert" in prompt_arg


@pytest.mark.asyncio
async def test_run_daily_briefing_persists_hrv_only_summary_and_reports_data_available():
    """HRV-only data should still be auditable and should not report 0/1 data."""
    session = _FakeSession(run_queue=[1100, 1101])
    summary = PeriodSummary(
        period="daily",
        metrics={
            "hrv": {
                "avg_ms": 40.0,
                "min_ms": 25,
                "max_ms": 60,
                "sample_count": 18,
                "baseline_avg_ms": 52.0,
                "delta_pct_vs_baseline": -23.0,
            }
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Your HRV was lower yesterday. Not medical advice.",
        tokens_in=10,
        tokens_out=20,
        model="ollama/llama3.1:8b",
        insight_type="daily_briefing",
    )

    engine = _make_engine(session, summary, llm_mock)
    run_id = await engine.run_daily_briefing()

    assert run_id == 1100
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 1
    assert findings[0]["finding_type"] == "summary"
    assert findings[0]["metric"] == "hrv"
    prompt_arg = llm_mock.generate_insight.await_args.args[0]
    assert "Data sufficiency: 1/1 days of history." in prompt_arg


@pytest.mark.asyncio
async def test_run_daily_briefing_anomaly_detector_failure_does_not_fail_the_briefing():
    """Detector errors are swallowed; briefing proceeds with an empty anomaly list."""
    session = _FakeSession(run_queue=[1000, 1001])
    summary = PeriodSummary(
        period="daily",
        metrics={
            "heart_rate": {
                "avg_bpm": 68.0,
                "min_bpm": 55,
                "max_bpm": 120,
                "sample_count": 24,
                "baseline_avg_bpm": 65.0,
                "delta_pct_vs_baseline": 4.6,
            }
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="All clear. Not medical advice.",
        tokens_in=10,
        tokens_out=20,
        model="ollama/llama3.1:8b",
        insight_type="daily_briefing",
    )

    engine = _make_engine(session, summary, llm_mock)
    engine.config.analysis.anomaly_detection.enabled = True
    engine.anomaly_detector.detect = AsyncMock(side_effect=RuntimeError("boom"))

    run_id = await engine.run_daily_briefing()

    assert run_id == 1000
    # Only the HR summary finding is inserted - no anomalies.
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 1
    assert findings[0]["finding_type"] == "summary"

    # Prompt still well-formed.
    prompt_arg = llm_mock.generate_insight.await_args.args[0]
    assert "no unusual readings vs baseline" in prompt_arg


@pytest.mark.asyncio
async def test_run_anomaly_check_persists_findings_without_calling_llm():
    """``run_anomaly_check`` is the lightweight cron variant - no LLM."""
    session = _FakeSession(run_queue=[2000, 2001, 2002])
    llm_mock = AsyncMock()

    config = AnalysisConfig.model_validate({"analysis": {"anomaly_detection": {"enabled": True}}})

    def factory():
        return session

    engine = AnalysisEngine(factory, llm_mock, config)
    engine.anomaly_detector.detect = AsyncMock(
        return_value=[
            Anomaly(metric="heart_rate", magnitude=2.7, direction="up", severity="watch"),
            Anomaly(metric="hrv", magnitude=-3.2, direction="down", severity="alert"),
        ]
    )

    run_id = await engine.run_anomaly_check()

    assert run_id == 2000
    # analysis_runs row is ``anomaly_check``
    run_inserts = session.all_insert_params_for("analysis_runs")
    assert len(run_inserts) == 1
    assert run_inserts[0]["run_type"] == "anomaly_check"
    # Two anomaly finding rows.
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 2
    assert {f["metric"] for f in findings} == {"heart_rate", "hrv"}
    # Runs completes (not skipped).
    updates = session.all_update_statements()
    assert any("status = 'completed'" in sql for sql, _ in updates)
    # LLM never called.
    llm_mock.generate_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_anomaly_check_skips_when_detector_finds_nothing():
    """Empty anomaly list → skipped run, no findings inserted."""
    session = _FakeSession(run_queue=[3000])
    llm_mock = AsyncMock()
    config = AnalysisConfig.model_validate({"analysis": {"anomaly_detection": {"enabled": True}}})

    def factory():
        return session

    engine = AnalysisEngine(factory, llm_mock, config)
    engine.anomaly_detector.detect = AsyncMock(return_value=[])

    run_id = await engine.run_anomaly_check()

    assert run_id is None
    assert session.all_insert_params_for("analysis_findings") == []
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)


@pytest.mark.asyncio
async def test_run_anomaly_check_respects_recent_cooldown_without_creating_run():
    """Cooldown is checked before creating another analysis_runs row."""
    session = _FakeSession(run_queue=[4000], select_queue=[[_Row(id=3999)]])
    llm_mock = AsyncMock()
    config = AnalysisConfig.model_validate(
        {"analysis": {"anomaly_detection": {"enabled": True, "cooldown_minutes": 15}}}
    )

    def factory():
        return session

    engine = AnalysisEngine(factory, llm_mock, config)
    engine.anomaly_detector.detect = AsyncMock(return_value=[])

    run_id = await engine.run_anomaly_check()

    assert run_id is None
    assert session.all_insert_params_for("analysis_runs") == []
    engine.anomaly_detector.detect.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_anomaly_check_dedupes_already_persisted_anomalies():
    """Rolling checks should not insert the same anomaly every cron tick."""
    observed_at = "2026-04-19T12:00:00+00:00"
    existing = _Row(
        metric="heart_rate",
        structured_data={
            "metric": "heart_rate",
            "detected_at": observed_at,
            "direction": "up",
        },
    )
    session = _FakeSession(run_queue=[5000, 5001], select_queue=[[], [existing]])
    llm_mock = AsyncMock()
    config = AnalysisConfig.model_validate(
        {"analysis": {"anomaly_detection": {"enabled": True, "cooldown_minutes": 15}}}
    )

    def factory():
        return session

    engine = AnalysisEngine(factory, llm_mock, config)
    engine.anomaly_detector.detect = AsyncMock(
        return_value=[
            Anomaly(
                metric="heart_rate",
                magnitude=3.0,
                direction="up",
                severity="alert",
                detected_at=datetime.fromisoformat(observed_at),
            ),
            Anomaly(metric="hrv", magnitude=-3.2, direction="down", severity="alert"),
        ]
    )

    run_id = await engine.run_anomaly_check()

    assert run_id == 5000
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 1
    assert findings[0]["metric"] == "hrv"


@pytest.mark.asyncio
async def test_run_trend_analysis_persists_detected_trends_without_calling_llm():
    """Phase 2b: trend analysis stores structured trend findings only."""
    session = _FakeSession(run_queue=[6000, 6001, 6002])
    config = AnalysisConfig.model_validate({"analysis": {"trend_analysis": {"enabled": True}}})
    engine = _make_plain_engine(session, config)
    engine.trend_analyzer.analyze = AsyncMock(
        side_effect=[
            Trend(
                metric="heart_rate",
                slope=0.42,
                direction="up",
                period_days=30,
                p_value=0.004,
                confidence="high",
            ),
            Trend(
                metric="hrv",
                slope=-0.9,
                direction="down",
                period_days=30,
                p_value=0.02,
                confidence="medium",
            ),
        ]
    )

    findings = await engine.run_trend_analysis()

    assert [finding.metric for finding in findings] == ["heart_rate", "hrv"]
    run_inserts = session.all_insert_params_for("analysis_runs")
    assert run_inserts[0]["run_type"] == "trend_analysis"
    finding_inserts = session.all_insert_params_for("analysis_findings")
    assert len(finding_inserts) == 2
    assert {row["finding_type"] for row in finding_inserts} == {"trend"}
    assert finding_inserts[0]["metric"] == "heart_rate"
    assert '"slope": 0.42' in finding_inserts[0]["structured_data"]
    updates = session.all_update_statements()
    assert any("status = 'completed'" in sql for sql, _ in updates)
    engine.llm_client.generate_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_trend_analysis_skips_when_no_metric_has_significant_trend():
    session = _FakeSession(run_queue=[7000])
    config = AnalysisConfig.model_validate({"analysis": {"trend_analysis": {"enabled": True}}})
    engine = _make_plain_engine(session, config)
    engine.trend_analyzer.analyze = AsyncMock(side_effect=[None, None])

    findings = await engine.run_trend_analysis()

    assert findings == []
    assert session.all_insert_params_for("analysis_findings") == []
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)


@pytest.mark.asyncio
async def test_run_correlation_analysis_persists_findings_strongest_first():
    """Phase 2b: correlations become structured findings, ranked, no LLM."""
    session = _FakeSession(run_queue=[8000, 8001, 8002])
    config = AnalysisConfig.model_validate(
        {"analysis": {"correlation_analysis": {"enabled": True}}}
    )
    engine = _make_plain_engine(session, config)
    engine.correlation_analyzer.analyze = AsyncMock(
        return_value=[
            Correlation(
                metric_a="vital.hrv_sdnn",
                metric_b="vital.resting_heart_rate",
                coefficient=-0.82,
                period_days=90,
                p_value=0.0001,
            ),
            Correlation(
                metric_a="activity.steps",
                metric_b="activity.active_energy",
                coefficient=0.61,
                period_days=90,
                p_value=0.002,
            ),
        ]
    )

    findings = await engine.run_correlation_analysis()

    assert [f.metric for f in findings] == [
        "vital.hrv_sdnn~vital.resting_heart_rate",
        "activity.steps~activity.active_energy",
    ]
    run_inserts = session.all_insert_params_for("analysis_runs")
    assert run_inserts[0]["run_type"] == "correlation_analysis"
    finding_inserts = session.all_insert_params_for("analysis_findings")
    assert len(finding_inserts) == 2
    assert {row["finding_type"] for row in finding_inserts} == {"correlation"}
    assert '"coefficient": -0.82' in finding_inserts[0]["structured_data"]
    updates = session.all_update_statements()
    assert any("status = 'completed'" in sql for sql, _ in updates)
    engine.llm_client.generate_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_correlation_analysis_skips_when_no_correlations():
    session = _FakeSession(run_queue=[9000])
    config = AnalysisConfig.model_validate(
        {"analysis": {"correlation_analysis": {"enabled": True}}}
    )
    engine = _make_plain_engine(session, config)
    engine.correlation_analyzer.analyze = AsyncMock(return_value=[])

    findings = await engine.run_correlation_analysis()

    assert findings == []
    assert session.all_insert_params_for("analysis_findings") == []
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)


@pytest.mark.asyncio
async def test_run_recovery_check_persists_recovery_score_finding_without_llm():
    """Recovery check maps the daily summary to one recovery_score finding."""
    session = _FakeSession(run_queue=[8500, 8501])  # run_id=8500, finding_id=8501
    summary = PeriodSummary(
        period="daily",
        metrics={
            "vital.hrv_sdnn": {
                "avg": 60.0,
                "baseline_avg": 50.0,
                "delta_pct_vs_baseline": 20.0,
                "sample_count": 1,
            },
            "vital.resting_heart_rate": {
                "avg": 48.0,
                "baseline_avg": 52.0,
                "delta_pct_vs_baseline": -7.7,
                "sample_count": 1,
            },
        },
    )
    engine = _make_engine(session, summary, AsyncMock())

    run_id = await engine.run_recovery_check()

    assert run_id == 8500
    run_inserts = session.all_insert_params_for("analysis_runs")
    assert run_inserts[0]["run_type"] == "recovery_check"
    finding_inserts = session.all_insert_params_for("analysis_findings")
    assert len(finding_inserts) == 1
    assert finding_inserts[0]["finding_type"] == "recovery_score"
    assert finding_inserts[0]["metric"] == "recovery"
    assert '"score":' in finding_inserts[0]["structured_data"]
    updates = session.all_update_statements()
    assert any("status = 'completed'" in sql for sql, _ in updates)
    engine.llm_client.generate_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_recovery_check_skips_when_no_signal_present():
    """No usable recovery signal → skipped run, no fabricated score persisted."""
    session = _FakeSession(run_queue=[8600])
    engine = _make_engine(session, PeriodSummary(period="daily", metrics={}), AsyncMock())

    run_id = await engine.run_recovery_check()

    assert run_id is None
    assert session.all_insert_params_for("analysis_findings") == []
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)


@pytest.mark.asyncio
async def test_fetch_metric_daily_series_maps_rows_to_day_value_and_skips_nulls(monkeypatch):
    """The injected fetcher turns canonical daily rows into a {day: value} map,
    dropping rows missing a day or value."""
    import storage.timescale.analysis as analysis_sql

    d1, d2 = date(2026, 5, 1), date(2026, 5, 2)
    canned = [
        _Row(day=d1, value=55.0, sample_count=10),
        _Row(day=d2, value=58.0, sample_count=12),
        _Row(day=None, value=99.0, sample_count=1),  # no day → dropped
        _Row(day=date(2026, 5, 3), value=None, sample_count=0),  # no value → dropped
    ]

    async def fake_fetch(session, metric_id, start, end, **kwargs):
        return canned

    monkeypatch.setattr(analysis_sql, "fetch_metric_daily_series", fake_fetch)

    engine = _make_plain_engine(_FakeSession(run_queue=[]))
    series = await engine._fetch_metric_daily_series("vital.hrv_sdnn", days=90)

    assert series == {d1: 55.0, d2: 58.0}


@pytest.mark.asyncio
async def test_fetch_trend_daily_values_falls_back_to_raw_heart_rate(monkeypatch):
    """The engine adapter owns storage-specific HR hourly/raw fallback."""
    import storage.timescale.analysis as analysis_sql

    calls: list[str] = []
    raw_rows = [_Row(day=date(2026, 5, 1), value=72.0, sample_count=24)]

    async def fake_hourly(session, start, end):
        calls.append("hourly")
        return []

    async def fake_raw(session, start, end):
        calls.append("raw")
        return raw_rows

    monkeypatch.setattr(analysis_sql, "fetch_heart_rate_daily_from_hourly", fake_hourly)
    monkeypatch.setattr(analysis_sql, "fetch_heart_rate_daily_from_raw", fake_raw)

    engine = _make_plain_engine(_FakeSession(run_queue=[]))
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 6, 1, tzinfo=UTC)

    rows = await engine._fetch_trend_daily_values("heart_rate", start, end)

    assert rows == raw_rows
    assert calls == ["hourly", "raw"]


@pytest.mark.asyncio
async def test_run_daily_briefing_folds_recent_trends_and_correlations_into_prompt():
    """The briefing surfaces the latest persisted trend + correlation findings."""
    # run_id=1200, hr_finding=1201; then two SELECTs (trends, correlations).
    trend_rows = [
        _Row(
            id=1,
            metric="heart_rate",
            severity=None,
            structured_data={
                "metric": "heart_rate",
                "direction": "down",
                "slope": -0.5,
                "p_value": 0.01,
            },
            created_at=datetime(2026, 5, 1),
        )
    ]
    corr_rows = [
        _Row(
            id=2,
            metric="vital.hrv_sdnn~vital.resting_heart_rate",
            severity=None,
            structured_data={
                "metric_a": "vital.hrv_sdnn",
                "metric_b": "vital.resting_heart_rate",
                "coefficient": -0.8,
                "method": "spearman",
            },
            created_at=datetime(2026, 5, 1),
        )
    ]
    session = _FakeSession(run_queue=[1200, 1201], select_queue=[trend_rows, corr_rows])
    summary = PeriodSummary(
        period="daily",
        metrics={"heart_rate": {"avg_bpm": 64.0, "sample_count": 24}},
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="All steady. Not medical advice.",
        tokens_in=5,
        tokens_out=5,
        model="ollama/llama3.1:8b",
        insight_type="daily_briefing",
    )

    engine = _make_engine(session, summary, llm_mock)
    await engine.run_daily_briefing()

    prompt = llm_mock.generate_insight.await_args.args[0]
    assert "heart_rate: down trend" in prompt
    assert "vital.hrv_sdnn ~ vital.resting_heart_rate" in prompt


@pytest.mark.asyncio
async def test_run_weekly_summary_success_writes_run_finding_and_insight():
    session = _FakeSession(run_queue=[700, 701])  # run_id=700, finding_id=701
    summary = PeriodSummary(
        period="weekly",
        metrics={
            "hrv": {
                "avg_ms": 48.0,
                "sample_count": 120,
                "baseline_avg_ms": 52.0,
                "delta_pct_vs_baseline": -7.7,
            }
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.return_value = InsightResult(
        narrative="Recovery dipped this week. Not medical advice.",
        tokens_in=60,
        tokens_out=120,
        model="ollama/llama3.1:8b",
        insight_type="weekly_summary",
    )

    config = AnalysisConfig.model_validate({"analysis": {"weekly_summary": {"enabled": True}}})
    engine = AnalysisEngine(lambda: session, llm_mock, config)
    engine.aggregator.summarize_period = AsyncMock(return_value=summary)

    run_id = await engine.run_weekly_summary()

    assert run_id == 700
    run_inserts = session.all_insert_params_for("analysis_runs")
    assert run_inserts[0]["run_type"] == "weekly_summary"
    insight_inserts = session.all_insert_params_for("analysis_insights")
    assert insight_inserts[0]["insight_type"] == "weekly_summary"
    assert insight_inserts[0]["findings_used"] == [701]
    # Week-over-baseline delta was folded into the prompt.
    prompt = llm_mock.generate_insight.await_args.args[0]
    assert "hrv: -7.7% vs 30-day baseline" in prompt
    updates = session.all_update_statements()
    assert any(
        "status = 'completed'" in sql and params.get("tokens_in") == 60 for sql, params in updates
    )


@pytest.mark.asyncio
async def test_run_weekly_summary_skips_when_no_data():
    session = _FakeSession(run_queue=[800])
    llm_mock = AsyncMock()
    config = AnalysisConfig.model_validate({"analysis": {"weekly_summary": {"enabled": True}}})
    engine = AnalysisEngine(lambda: session, llm_mock, config)
    engine.aggregator.summarize_period = AsyncMock(
        return_value=PeriodSummary(period="weekly", metrics={})
    )

    run_id = await engine.run_weekly_summary()

    assert run_id is None
    llm_mock.generate_insight.assert_not_awaited()
    updates = session.all_update_statements()
    assert any("status = 'skipped'" in sql for sql, _ in updates)


@pytest.mark.asyncio
async def test_run_daily_briefing_marks_failed_when_llm_raises():
    session = _FakeSession(run_queue=[404, 505])
    summary = PeriodSummary(
        period="daily",
        metrics={
            "heart_rate": {
                "avg_bpm": 70.0,
                "min_bpm": 60,
                "max_bpm": 130,
                "sample_count": 24,
                "baseline_avg_bpm": None,
                "delta_pct_vs_baseline": None,
            }
        },
    )
    llm_mock = AsyncMock()
    llm_mock.generate_insight.side_effect = LLMUnavailableError("ollama unreachable")

    engine = _make_engine(session, summary, llm_mock)
    with pytest.raises(LLMUnavailableError):
        await engine.run_daily_briefing()

    updates = session.all_update_statements()
    failed_update = [(sql, params) for sql, params in updates if "status = 'failed'" in sql]
    assert failed_update, "expected an UPDATE ... status = 'failed' statement"
    assert "ollama unreachable" in failed_update[0][1]["error"]
    assert session.committed is True
