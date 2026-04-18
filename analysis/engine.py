"""Analysis engine — orchestrator for statistical + LLM runs.

Phase 1 ships only the class shape. Each method raises
``NotImplementedError`` with a pointer to Phase 1.5 where the real
run logic lands.
"""

from .types import Finding, Insight


class AnalysisEngine:
    """Top-level orchestrator.

    Composes the Brain-1 statistical pipeline (aggregator → anomaly /
    trend / correlation / scoring) with the Brain-2 LLM narrator into
    analysis runs. Each public method represents one scheduled job
    type declared in ``config.yaml``.
    """

    def __init__(self, session_factory, config, llm_client) -> None:
        """Store collaborators; real setup happens in Phase 1.5."""
        self.session_factory = session_factory
        self.config = config
        self.llm_client = llm_client

    async def run_daily_briefing(self) -> Insight:
        """Produce yesterday's narrative morning briefing."""
        raise NotImplementedError(
            "Daily briefing run deferred to Phase 1.5 — engine scaffolding only"
        )

    async def run_weekly_summary(self) -> Insight:
        """Produce the weekly rollup narrative."""
        raise NotImplementedError(
            "Weekly summary run deferred to Phase 1.5 — engine scaffolding only"
        )

    async def run_anomaly_check(self, quick: bool = False) -> list[Finding]:
        """Scan for fresh anomalies since the last run."""
        raise NotImplementedError(
            "Anomaly check run deferred to Phase 1.5 — engine scaffolding only"
        )

    async def run_trend_analysis(self) -> list[Finding]:
        """Compute trend findings across enabled metrics."""
        raise NotImplementedError(
            "Trend analysis run deferred to Phase 1.5 — engine scaffolding only"
        )

    async def run_correlation_analysis(self) -> list[Finding]:
        """Compute Spearman correlations for the configured metric pairs."""
        raise NotImplementedError(
            "Correlation analysis run deferred to Phase 1.5 — engine scaffolding only"
        )
