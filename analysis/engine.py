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
from datetime import UTC, datetime

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
        run_id: int | None = None
        async with self.session_factory() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO analysis_runs (run_type, status, started_at)
                        VALUES ('daily_briefing', 'running', :now)
                        RETURNING id
                        """
                    ),
                    {"now": datetime.now(tz=UTC)},
                )
                row = result.fetchone()
                run_id = row.id if row is not None else None

                summary = await self.aggregator.summarize_period(period="daily", days=1)

                if not summary.metrics:
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
                    await session.commit()
                    return None

                hr = summary.metrics.get("heart_rate")
                finding_ids: list[int] = []
                if hr is not None:
                    hr_finding_id = await self._insert_finding(
                        session,
                        run_id=run_id,
                        finding=Finding(
                            finding_type="summary",
                            metric="heart_rate",
                            severity="info",
                            structured_data=hr,
                        ),
                    )
                    if hr_finding_id is not None:
                        finding_ids.append(hr_finding_id)

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
                    days_of_data=(hr or {}).get("sample_count", 0),
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
                        "provider": insight_result.model,
                        "tokens_in": insight_result.tokens_in,
                        "tokens_out": insight_result.tokens_out,
                        "id": run_id,
                    },
                )
                await session.commit()
                return run_id
            except Exception as exc:
                # Best-effort failure marking. If the original failure left the
                # session in an unrecoverable state, we still re-raise the
                # ORIGINAL exception — callers want the root cause, not a
                # bookkeeping error that masks it.
                if run_id is not None:
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
                            {
                                "now": datetime.now(tz=UTC),
                                "error": str(exc),
                                "id": run_id,
                            },
                        )
                        await session.commit()
                    except Exception:
                        pass
                raise

    async def run_anomaly_check(self) -> int | None:
        """Lightweight detector run with no LLM narration.

        Persists an ``analysis_runs`` row with ``run_type='anomaly_check'``
        and writes each detected anomaly as an ``analysis_findings`` row.
        Returns the run id on completion, or ``None`` when the run was
        skipped because the detector found nothing.
        """
        run_id: int | None = None
        async with self.session_factory() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO analysis_runs (run_type, status, started_at)
                        VALUES ('anomaly_check', 'running', :now)
                        RETURNING id
                        """
                    ),
                    {"now": datetime.now(tz=UTC)},
                )
                row = result.fetchone()
                run_id = row.id if row is not None else None

                anomalies = await self.anomaly_detector.detect(lookback_days=1)

                if not anomalies:
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

                await session.execute(
                    text(
                        """
                        UPDATE analysis_runs
                           SET status = 'completed',
                               completed_at = :now
                         WHERE id = :id
                        """
                    ),
                    {"now": datetime.now(tz=UTC), "id": run_id},
                )
                await session.commit()
                return run_id
            except Exception as exc:
                if run_id is not None:
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
                            {
                                "now": datetime.now(tz=UTC),
                                "error": str(exc),
                                "id": run_id,
                            },
                        )
                        await session.commit()
                    except Exception:
                        pass
                raise

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
            return await self.anomaly_detector.detect(lookback_days=1)
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
