"""Analysis engine - orchestrator for statistical + LLM runs.

Phase 2 activation: ``run_daily_briefing`` now also runs the anomaly
detector, persists each anomaly as an ``analysis_findings`` row, and
feeds a formatted anomaly bullet list into the prompt. A lightweight
sibling, ``run_anomaly_check``, runs the same detector on a 30-minute
cron without touching the LLM. Phase 2b adds trend analysis as another
structured Brain-1-only run. Weekly summaries and correlations still
raise ``NotImplementedError`` pointing at Phase 2b.

Phase 5F lifted every SQL statement out of this module into
``storage.timescale.analysis``. The orchestrator below now composes
those storage helpers with the LLM client and the statistical
collaborators (aggregator / anomaly / trend). No ``import sqlalchemy``
remains here — the storage zone invariant
(``tests/contract/test_storage_invariant.py``) is what enforces it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar

from .llm.prompts.daily_briefing import DAILY_BRIEFING_PROMPT_TEMPLATE
from .statistical.aggregator import DataAggregator
from .statistical.anomaly import AnomalyDetector
from .statistical.correlations import CorrelationAnalyzer
from .statistical.trends import TrendAnalyzer
from .types import Anomaly, Finding, Insight


def _sql():
    """Lazy import handle for ``storage.timescale.analysis``.

    Eager `from storage.timescale import analysis` re-introduces the
    same circular-import that bit Phase 5C/5E:

      analysis.engine
        → storage.timescale.__init__ (imports `measurements`)
          → server.ingestion.mappers (triggers server.__init__)
            → server.ingestion.handlers shim
              → storage.timescale.measurements (still loading) — boom

    Tests that import analysis.engine without first importing server
    (e.g. test_analysis_engine.py) trip the cycle. Lazy-import keeps
    the storage hop deferred until the first DB call, by which point
    server has been pre-loaded by the FastAPI app or earlier test
    fixtures. Mirrors the pattern in storage/timescale/ingest.py.
    """
    from storage.timescale import analysis as analysis_sql

    return analysis_sql


log = logging.getLogger("healthsave.analysis")

_TREND_METRICS = ("heart_rate", "hrv")
_T = TypeVar("_T")


class AnalysisEngine:
    """Top-level orchestrator.

    Composes the Brain-1 statistical pipeline (aggregator → anomaly /
    trend / correlation / scoring) with the Brain-2 LLM narrator into
    analysis runs. Phase 2 wires daily-briefing + anomaly-check
    end-to-end; the rest arrive in Phase 2b.
    """

    def __init__(self, session_factory, llm_client, config) -> None:
        """Store collaborators. The aggregator is owned by the engine."""
        self.session_factory = session_factory
        self.config = config
        self.llm_client = llm_client
        self.aggregator = DataAggregator(session_factory)
        self.anomaly_detector = AnomalyDetector(session_factory, config)
        self.trend_analyzer = TrendAnalyzer(session_factory)
        self.correlation_analyzer = CorrelationAnalyzer(self._fetch_metric_daily_series)

    async def run_daily_briefing(self) -> int | None:
        return await self._run_job_with_metrics("daily_briefing", self._run_daily_briefing_impl)

    async def _run_daily_briefing_impl(self) -> int | None:
        """Produce yesterday's narrative morning briefing.

        Returns the newly-created ``analysis_runs.id`` on a completed run,
        or ``None`` when the run was skipped (no data in the lookback
        window). Skipped runs still persist a row in ``analysis_runs``
        for audit; callers that need that id can join via the
        completed_at timestamp. Re-raises on failure after marking the
        run ``failed`` with an error message.
        """
        async with (
            self.session_factory() as session,
            self._run_context(session, "daily_briefing") as run_id,
        ):
            summary = await self.aggregator.summarize_period(period="daily", days=1)

            if not summary.metrics:
                await _sql().mark_run_skipped(session, run_id)
                await session.commit()
                return None

            finding_ids: list[int] = []
            for metric, metric_summary in summary.metrics.items():
                summary_finding_id = await self._insert_finding(
                    session,
                    run_id=run_id,
                    finding=Finding(
                        finding_type="summary",
                        metric=metric,
                        severity="info",
                        structured_data=metric_summary,
                    ),
                )
                if summary_finding_id is not None:
                    finding_ids.append(summary_finding_id)

            anomalies = await self._detect_anomalies_safely()
            for anomaly in anomalies:
                anomaly_finding_id = await self._insert_finding(
                    session,
                    run_id=run_id,
                    finding=Finding(
                        finding_type="anomaly",
                        metric=anomaly.metric,
                        severity=anomaly.severity,
                        structured_data=anomaly.model_dump(mode="json"),
                    ),
                )
                if anomaly_finding_id is not None:
                    finding_ids.append(anomaly_finding_id)

            prompt = DAILY_BRIEFING_PROMPT_TEMPLATE.format(
                period_summary=json.dumps(summary.metrics, indent=2, default=str),
                anomalies=_format_anomalies_for_prompt(anomalies),
                trends="(trend analysis runs separately; see /api/insights/trends)",
                correlations="(correlation analysis runs separately as a Brain-1 job)",
                days_of_data=_daily_data_days(summary.metrics),
                minimum_required=1,
            )

            insight_result = await self.llm_client.generate_insight(
                prompt, insight_type="daily_briefing"
            )

            insight = Insight(
                insight_type="daily_briefing",
                narrative=insight_result.narrative,
                findings_used=finding_ids,
            )

            await self._insert_insight(session, insight=insight, run_id=run_id)

            await _sql().mark_run_completed(
                session,
                run_id,
                llm_provider=insight_result.model,
                llm_tokens_in=insight_result.tokens_in,
                llm_tokens_out=insight_result.tokens_out,
            )
            await session.commit()
            return run_id

    async def run_anomaly_check(self) -> int | None:
        return await self._run_job_with_metrics("anomaly_check", self._run_anomaly_check_impl)

    async def _run_anomaly_check_impl(self) -> int | None:
        """Lightweight detector run with no LLM narration.

        Persists an ``analysis_runs`` row with ``run_type='anomaly_check'``
        and writes each detected anomaly as an ``analysis_findings`` row.
        Returns the run id on completion, or ``None`` when the run was
        skipped because the detector found nothing.
        """
        async with self.session_factory() as session:
            cooldown_minutes = self.config.analysis.anomaly_detection.cooldown_minutes
            if await _sql().within_cooldown(session, "anomaly_check", cooldown_minutes):
                return None

            async with self._run_context(session, "anomaly_check") as run_id:
                anomalies = await self.anomaly_detector.detect(lookback_days=1)
                anomalies = await self._filter_existing_anomalies(session, anomalies)

                if not anomalies:
                    await _sql().mark_run_skipped(session, run_id)
                    await session.commit()
                    return None

                for anomaly in anomalies:
                    await self._insert_finding(
                        session,
                        run_id=run_id,
                        finding=Finding(
                            finding_type="anomaly",
                            metric=anomaly.metric,
                            severity=anomaly.severity,
                            structured_data=anomaly.model_dump(mode="json"),
                        ),
                    )

                await _sql().mark_run_completed(session, run_id)
                await session.commit()
                return run_id

    async def run_weekly_summary(self) -> Insight:
        """Produce the weekly rollup narrative."""
        raise NotImplementedError(
            "Weekly summary run deferred to Phase 2b - "
            "current scope is daily briefing + anomaly check"
        )

    async def run_trend_analysis(self) -> list[Finding]:
        return await self._run_job_with_metrics("trend_analysis", self._run_trend_analysis_impl)

    async def _run_trend_analysis_impl(self) -> list[Finding]:
        """Compute trend findings across enabled metrics."""
        async with (
            self.session_factory() as session,
            self._run_context(session, "trend_analysis") as run_id,
        ):
            trends = []
            period_days = self.config.analysis.trend_analysis.period_days
            for metric in _TREND_METRICS:
                trend = await self.trend_analyzer.analyze(metric, days=period_days)
                if trend is not None:
                    trends.append(trend)

            if not trends:
                await _sql().mark_run_skipped(session, run_id)
                await session.commit()
                return []

            findings: list[Finding] = []
            for trend in trends:
                finding = Finding(
                    finding_type="trend",
                    metric=trend.metric,
                    severity="info",
                    structured_data=trend.model_dump(mode="json"),
                )
                await self._insert_finding(session, run_id=run_id, finding=finding)
                findings.append(finding)

            await _sql().mark_run_completed(session, run_id)
            await session.commit()
            return findings

    async def run_correlation_analysis(self) -> list[Finding]:
        return await self._run_job_with_metrics(
            "correlation_analysis", self._run_correlation_analysis_impl
        )

    async def _run_correlation_analysis_impl(self) -> list[Finding]:
        """Persist Spearman correlations for the configured metric pairs.

        Brain-1-only (no LLM): each significant, non-trivial correlation
        becomes a ``correlation`` finding, strongest-first — the order is the
        candidate ranking for an eventual n-of-1 experiment. No correlations
        (insufficient/misaligned data, or nothing meaningful) → skipped run.
        """
        async with (
            self.session_factory() as session,
            self._run_context(session, "correlation_analysis") as run_id,
        ):
            period_days = self.config.analysis.correlation_analysis.period_days
            correlations = await self.correlation_analyzer.analyze(days=period_days)

            if not correlations:
                await _sql().mark_run_skipped(session, run_id)
                await session.commit()
                return []

            findings: list[Finding] = []
            for correlation in correlations:
                finding = Finding(
                    finding_type="correlation",
                    metric=f"{correlation.metric_a}~{correlation.metric_b}",
                    severity="info",
                    structured_data=correlation.model_dump(mode="json"),
                )
                await self._insert_finding(session, run_id=run_id, finding=finding)
                findings.append(finding)

            await _sql().mark_run_completed(session, run_id)
            await session.commit()
            return findings

    async def _fetch_metric_daily_series(self, metric_id: str, days: int) -> dict[date, float]:
        """Daily-series fetcher injected into :class:`CorrelationAnalyzer`.

        Reads the canonical store (via the storage zone) for ``metric_id`` over
        the trailing ``days`` window and returns a ``{day: mean_value}`` map.
        Opens its own session per metric, mirroring how the trend analyzer
        self-manages reads.
        """
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        async with self.session_factory() as session:
            rows = await _sql().fetch_metric_daily_series(session, metric_id, start, end)
        return {
            row.day: float(row.value)
            for row in rows
            if getattr(row, "value", None) is not None and getattr(row, "day", None) is not None
        }

    # ──────────────────────────────────────────────────────────────
    #  Internals
    # ──────────────────────────────────────────────────────────────

    async def _run_job_with_metrics(self, job: str, runner: Callable[[], Awaitable[_T]]) -> _T:
        # Lazy import: server.api.metrics → server.main → analysis.engine would cycle.
        from server.api.metrics import AI_BRIEFING_RUNS

        try:
            result = await runner()
        except Exception:
            AI_BRIEFING_RUNS.labels(job=job, result="failure").inc()
            raise

        AI_BRIEFING_RUNS.labels(job=job, result="success").inc()
        return result

    @asynccontextmanager
    async def _run_context(self, session, run_type: str):
        """Lifecycle wrapper for an ``analysis_runs`` row.

        Yields the new ``run_id``. On exception inside the block, marks
        the run ``failed`` (best-effort) and re-raises the ORIGINAL
        exception - callers want the root cause, not a bookkeeping
        error that masks it.
        """
        run_id = await _sql().begin_run(session, run_type)
        try:
            yield run_id
        except Exception as exc:
            await self._mark_run_failed(session, run_id, exc)
            raise

    async def _mark_run_failed(self, session, run_id: int | None, exc: Exception) -> None:
        """Best-effort ``status='failed'`` UPDATE. Swallows secondary errors so the
        ORIGINAL exception from the caller is what propagates.
        """
        if run_id is None:
            return
        try:
            await _sql().mark_run_failed(session, run_id, str(exc))
        except Exception:
            log.exception("failed to mark analysis_runs.id=%s as failed", run_id)

    async def _insert_finding(self, session, *, run_id: int | None, finding: Finding) -> int | None:
        """Persist one finding via the storage helper and return its id."""
        return await _sql().insert_finding(
            session,
            run_id=run_id,
            finding_type=finding.finding_type,
            metric=finding.metric,
            severity=finding.severity,
            structured_data=finding.structured_data,
        )

    async def _insert_insight(self, session, *, insight: Insight, run_id: int | None) -> None:
        """Persist a narrative insight row via the storage helper."""
        await _sql().insert_insight(
            session,
            run_id=run_id,
            insight_type=insight.insight_type,
            narrative=insight.narrative,
            findings_used=insight.findings_used,
        )

    async def _filter_existing_anomalies(self, session, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Suppress anomalies already persisted by earlier rolling checks."""
        if not anomalies:
            return []

        detected_times = [a.detected_at for a in anomalies if a.detected_at is not None]
        since = min(detected_times) - timedelta(days=1) if detected_times else datetime.now(tz=UTC)
        rows = await _sql().fetch_recent_anomaly_findings(session, since)
        existing = {
            _anomaly_key_from_data(metric, structured_data) for metric, structured_data in rows
        }
        return [anomaly for anomaly in anomalies if _anomaly_key(anomaly) not in existing]

    async def _detect_anomalies_safely(self) -> list[Anomaly]:
        """Run the detector, swallowing errors so the briefing keeps flowing.

        Anomaly detection is a *nice to have* for the narrative; a SQL
        hiccup or missing table shouldn't kill the whole daily briefing.
        Log at warning level so operators notice, return ``[]`` to keep
        the prompt well-formed.
        """
        if not self.config.analysis.anomaly_detection.enabled:
            return []
        try:
            end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            return await self.anomaly_detector.detect(lookback_days=1, end_at=end)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("anomaly detection failed; continuing briefing: %s", exc)
            return []


def _format_anomalies_for_prompt(anomalies: list[Anomaly]) -> str:
    """Turn an anomaly list into a short bullet block for the LLM prompt."""
    if not anomalies:
        return "no unusual readings vs baseline"
    return "\n".join(
        f"- {a.metric}: {a.direction} deviation, severity={a.severity}, z={a.magnitude:.2f}"
        for a in anomalies
    )


def _daily_data_days(metrics: dict[str, dict]) -> int:
    """Daily briefing sufficiency is day-based, not sample-count based."""
    return 1 if any((metric.get("sample_count") or 0) > 0 for metric in metrics.values()) else 0


def _anomaly_key(anomaly: Anomaly) -> tuple[str, str | None, str]:
    detected_at = anomaly.detected_at.isoformat() if anomaly.detected_at is not None else None
    return (anomaly.metric, detected_at, anomaly.direction)


def _anomaly_key_from_data(
    metric: str | None, structured_data
) -> tuple[str | None, str | None, str | None]:
    if isinstance(structured_data, str):
        try:
            structured_data = json.loads(structured_data)
        except ValueError:
            structured_data = {}
    if not isinstance(structured_data, dict):
        structured_data = {}
    return (
        metric or structured_data.get("metric"),
        structured_data.get("detected_at"),
        structured_data.get("direction"),
    )
