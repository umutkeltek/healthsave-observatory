"""Analysis engine — orchestrator for statistical + LLM runs.

Phase 2 activation: ``run_daily_briefing`` now also runs the anomaly
detector, persists each anomaly as an ``analysis_findings`` row, and
feeds a formatted anomaly bullet list into the prompt. A lightweight
sibling, ``run_anomaly_check``, runs the same detector on a 30-minute
cron without touching the LLM. The remaining run types (weekly /
trends / correlations) still raise ``NotImplementedError`` pointing at
Phase 2b.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from .llm.prompts.daily_briefing import DAILY_BRIEFING_PROMPT_TEMPLATE
from .statistical.aggregator import DataAggregator
from .statistical.anomaly import AnomalyDetector
from .types import Anomaly, Finding, Insight

log = logging.getLogger("healthsave.analysis")


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

    async def run_daily_briefing(self) -> int | None:
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
                await self._mark_run_skipped(session, run_id)
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
                trends="(trend analysis deferred to Phase 2b)",
                correlations="(correlation analysis deferred to Phase 2b)",
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

            await session.execute(
                text(
                    """
                    INSERT INTO analysis_insights
                        (run_id, insight_type, narrative, findings_used)
                    VALUES (:run_id, :insight_type, :narrative, :findings_used)
                    """
                ),
                {
                    "run_id": run_id,
                    "insight_type": insight.insight_type,
                    "narrative": insight.narrative,
                    "findings_used": insight.findings_used,
                },
            )

            await self._mark_run_completed(
                session,
                run_id,
                llm_provider=insight_result.model,
                llm_tokens_in=insight_result.tokens_in,
                llm_tokens_out=insight_result.tokens_out,
            )
            await session.commit()
            return run_id

    async def run_anomaly_check(self) -> int | None:
        """Lightweight detector run with no LLM narration.

        Persists an ``analysis_runs`` row with ``run_type='anomaly_check'``
        and writes each detected anomaly as an ``analysis_findings`` row.
        Returns the run id on completion, or ``None`` when the run was
        skipped because the detector found nothing.
        """
        async with self.session_factory() as session:
            if await self._within_cooldown(session, "anomaly_check"):
                return None

            async with self._run_context(session, "anomaly_check") as run_id:
                anomalies = await self.anomaly_detector.detect(lookback_days=1)
                anomalies = await self._filter_existing_anomalies(session, anomalies)

                if not anomalies:
                    await self._mark_run_skipped(session, run_id)
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

                await self._mark_run_completed(session, run_id)
                await session.commit()
                return run_id

    async def run_weekly_summary(self) -> Insight:
        """Produce the weekly rollup narrative."""
        raise NotImplementedError(
            "Weekly summary run deferred to Phase 2b — "
            "current scope is daily briefing + anomaly check"
        )

    async def run_trend_analysis(self) -> list[Finding]:
        """Compute trend findings across enabled metrics."""
        raise NotImplementedError(
            "Trend analysis run deferred to Phase 2b — "
            "current scope is daily briefing + anomaly check"
        )

    async def run_correlation_analysis(self) -> list[Finding]:
        """Compute Spearman correlations for the configured metric pairs."""
        raise NotImplementedError(
            "Correlation analysis run deferred to Phase 2b — "
            "current scope is daily briefing + anomaly check"
        )

    # ──────────────────────────────────────────────────────────────
    #  Internals
    # ──────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def _run_context(self, session, run_type: str):
        """Lifecycle wrapper for an ``analysis_runs`` row.

        Yields the new ``run_id``. On exception inside the block, marks
        the run ``failed`` (best-effort) and re-raises the ORIGINAL
        exception — callers want the root cause, not a bookkeeping
        error that masks it.
        """
        run_id = await self._begin_run(session, run_type)
        try:
            yield run_id
        except Exception as exc:
            await self._mark_run_failed(session, run_id, exc)
            raise

    async def _begin_run(self, session, run_type: str) -> int | None:
        """Insert an ``analysis_runs`` row with ``status='running'`` and return its id."""
        result = await session.execute(
            text(
                """
                INSERT INTO analysis_runs (run_type, status, started_at)
                VALUES (:run_type, 'running', :now)
                RETURNING id
                """
            ),
            {"run_type": run_type, "now": datetime.now(tz=UTC)},
        )
        row = result.fetchone()
        return row.id if row is not None else None

    async def _mark_run_skipped(self, session, run_id: int | None) -> None:
        await session.execute(
            text(
                """
                UPDATE analysis_runs
                   SET status = 'skipped',
                       completed_at = :now
                 WHERE id = :id
                """
            ),
            {"now": datetime.now(tz=UTC), "id": run_id},
        )

    async def _mark_run_completed(
        self,
        session,
        run_id: int | None,
        *,
        llm_provider: str | None = None,
        llm_tokens_in: int | None = None,
        llm_tokens_out: int | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE analysis_runs
                   SET status = 'completed',
                       completed_at = :now,
                       llm_provider = :provider,
                       llm_tokens_in = :tokens_in,
                       llm_tokens_out = :tokens_out
                 WHERE id = :id
                """
            ),
            {
                "now": datetime.now(tz=UTC),
                "provider": llm_provider,
                "tokens_in": llm_tokens_in,
                "tokens_out": llm_tokens_out,
                "id": run_id,
            },
        )

    async def _mark_run_failed(self, session, run_id: int | None, exc: Exception) -> None:
        """Best-effort ``status='failed'`` UPDATE. Swallows secondary errors so the
        ORIGINAL exception from the caller is what propagates.
        """
        if run_id is None:
            return
        try:
            await session.execute(
                text(
                    """
                    UPDATE analysis_runs
                       SET status = 'failed',
                           completed_at = :now,
                           error_message = :error
                     WHERE id = :id
                    """
                ),
                {"now": datetime.now(tz=UTC), "error": str(exc), "id": run_id},
            )
            await session.commit()
        except Exception:
            log.exception("failed to mark analysis_runs.id=%s as failed", run_id)

    async def _insert_finding(self, session, *, run_id: int | None, finding: Finding) -> int | None:
        """Persist one finding and return its id (or None if the row failed)."""
        result = await session.execute(
            text(
                """
                INSERT INTO analysis_findings
                    (run_id, finding_type, metric, severity, structured_data)
                VALUES (:run_id, :finding_type, :metric, :severity, :structured_data)
                RETURNING id
                """
            ),
            {
                "run_id": run_id,
                "finding_type": finding.finding_type,
                "metric": finding.metric,
                "severity": finding.severity,
                "structured_data": json.dumps(finding.structured_data, default=str),
            },
        )
        row = result.fetchone()
        return row.id if row is not None else None

    async def _within_cooldown(self, session, run_type: str) -> bool:
        """Return True when a recent run makes another ad-hoc run redundant."""
        cooldown = self.config.analysis.anomaly_detection.cooldown_minutes
        if cooldown <= 0:
            return False
        since = datetime.now(tz=UTC) - timedelta(minutes=cooldown)
        result = await session.execute(
            text(
                """
                SELECT id
                FROM analysis_runs
                WHERE run_type = :run_type
                  AND started_at >= :since
                  AND status IN ('running', 'completed', 'skipped')
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"run_type": run_type, "since": since},
        )
        row = result.fetchone()
        return row is not None

    async def _filter_existing_anomalies(self, session, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Suppress anomalies already persisted by earlier rolling checks."""
        if not anomalies:
            return []

        detected_times = [a.detected_at for a in anomalies if a.detected_at is not None]
        since = min(detected_times) - timedelta(days=1) if detected_times else datetime.now(tz=UTC)
        result = await session.execute(
            text(
                """
                SELECT metric, structured_data
                FROM analysis_findings
                WHERE finding_type = 'anomaly'
                  AND created_at >= :since
                """
            ),
            {"since": since},
        )
        existing = {
            _anomaly_key_from_data(row.metric, row.structured_data)
            for row in self._fetchall(result)
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

    @staticmethod
    def _fetchall(result) -> list[Any]:
        fetchall = getattr(result, "fetchall", None)
        if callable(fetchall):
            rows = fetchall()
            return list(rows) if rows is not None else []
        try:
            return list(result)
        except TypeError:
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
