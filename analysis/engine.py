"""Analysis engine — orchestrator for statistical + LLM runs.

Phase 1.5 activation: ``run_daily_briefing`` now implements the full
end-to-end path (create run → aggregate → maybe LLM → persist →
complete). The remaining run types still raise ``NotImplementedError``
with a pointer to Phase 2.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from .llm.prompts.daily_briefing import DAILY_BRIEFING_PROMPT_TEMPLATE
from .statistical.aggregator import DataAggregator
from .types import Finding, Insight


class AnalysisEngine:
    """Top-level orchestrator.

    Composes the Brain-1 statistical pipeline (aggregator → anomaly /
    trend / correlation / scoring) with the Brain-2 LLM narrator into
    analysis runs. Phase 1.5 wires a single run type end-to-end; the
    rest arrive in Phase 2.
    """

    def __init__(self, session_factory, llm_client, config) -> None:
        """Store collaborators. The aggregator is owned by the engine."""
        self.session_factory = session_factory
        self.config = config
        self.llm_client = llm_client
        self.aggregator = DataAggregator(session_factory)

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

                hr = summary.metrics["heart_rate"]
                finding = Finding(
                    finding_type="summary",
                    metric="heart_rate",
                    severity="info",
                    structured_data=hr,
                )

                finding_result = await session.execute(
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
                        "structured_data": json.dumps(finding.structured_data),
                    },
                )
                finding_row = finding_result.fetchone()
                finding_id = finding_row.id if finding_row is not None else None

                prompt = DAILY_BRIEFING_PROMPT_TEMPLATE.format(
                    period_summary=json.dumps(hr, indent=2),
                    anomalies="(none detected in MVP scope)",
                    trends="(trend analysis deferred to Phase 2)",
                    correlations="(correlation analysis deferred to Phase 2)",
                    days_of_data=hr.get("sample_count", 0),
                    minimum_required=1,
                )

                insight_result = await self.llm_client.generate_insight(
                    prompt, insight_type="daily_briefing"
                )

                insight = Insight(
                    insight_type="daily_briefing",
                    narrative=insight_result.narrative,
                    findings_used=[finding_id] if finding_id is not None else [],
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

    async def run_weekly_summary(self) -> Insight:
        """Produce the weekly rollup narrative."""
        raise NotImplementedError(
            "Weekly summary run deferred to Phase 2 — MVP scope is daily briefing only"
        )

    async def run_anomaly_check(self, quick: bool = False) -> list[Finding]:
        """Scan for fresh anomalies since the last run."""
        raise NotImplementedError(
            "Anomaly check run deferred to Phase 2 — MVP scope is daily briefing only"
        )

    async def run_trend_analysis(self) -> list[Finding]:
        """Compute trend findings across enabled metrics."""
        raise NotImplementedError(
            "Trend analysis run deferred to Phase 2 — MVP scope is daily briefing only"
        )

    async def run_correlation_analysis(self) -> list[Finding]:
        """Compute Spearman correlations for the configured metric pairs."""
        raise NotImplementedError(
            "Correlation analysis run deferred to Phase 2 — MVP scope is daily briefing only"
        )
