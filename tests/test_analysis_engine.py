"""Unit tests for :class:`analysis.engine.AnalysisEngine.run_daily_briefing`.

Extends the Phase 1 ``FakeSession`` discipline: no live DB, async mock
stands in for the LLM client. Covers success, empty-summary skip, and
LLM-failure re-raise paths.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from analysis.engine import AnalysisEngine  # noqa: E402
from analysis.llm.client import InsightResult, LLMUnavailableError  # noqa: E402
from analysis.types import Anomaly, PeriodSummary  # noqa: E402


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSession:
    """Async session stub recording every SQL statement.

    ``run_queue`` supplies the ``RETURNING id`` rows (first call: run_id,
    second call: finding_id). Other ``execute`` calls return an empty
    ``_Result`` — the engine only reads rows from the INSERT...RETURNING
    statements.
    """

    def __init__(self, run_queue: list[int]):
        self.calls: list[tuple[str, dict]] = []
        self.committed = False
        self._queue = list(run_queue)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
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
    # run_id=900, hr_finding_id=901, anomaly_finding_id=902.
    session = _FakeSession(run_queue=[900, 901, 902])
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
    engine.anomaly_detector.detect = AsyncMock(
        return_value=[Anomaly(metric="hrv", magnitude=-3.1, direction="down", severity="alert")]
    )

    run_id = await engine.run_daily_briefing()

    assert run_id == 900
    # Two finding rows: HR summary + HRV anomaly
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 2
    assert findings[0]["finding_type"] == "summary"
    assert findings[0]["metric"] == "heart_rate"
    assert findings[1]["finding_type"] == "anomaly"
    assert findings[1]["metric"] == "hrv"
    assert findings[1]["severity"] == "alert"

    # Insight references BOTH finding ids.
    insight_inserts = session.all_insert_params_for("analysis_insights")
    assert insight_inserts[0]["findings_used"] == [901, 902]

    # Anomalies were formatted into the LLM prompt.
    prompt_arg = llm_mock.generate_insight.await_args.args[0]
    assert "hrv: down deviation" in prompt_arg
    assert "severity=alert" in prompt_arg


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
    engine.anomaly_detector.detect = AsyncMock(side_effect=RuntimeError("boom"))

    run_id = await engine.run_daily_briefing()

    assert run_id == 1000
    # Only the HR summary finding is inserted — no anomalies.
    findings = session.all_insert_params_for("analysis_findings")
    assert len(findings) == 1
    assert findings[0]["finding_type"] == "summary"

    # Prompt still well-formed.
    prompt_arg = llm_mock.generate_insight.await_args.args[0]
    assert "no unusual readings vs baseline" in prompt_arg


@pytest.mark.asyncio
async def test_run_anomaly_check_persists_findings_without_calling_llm():
    """``run_anomaly_check`` is the lightweight cron variant — no LLM."""
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
