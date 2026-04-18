"""Time-period data summarization.

Pulls from TimescaleDB continuous aggregates (``hr_hourly``,
``sleep_daily``, future ``hr_daily`` + ``activity_weekly``) and
produces a ``PeriodSummary`` compact enough for the LLM narrator.
"""

from ..types import PeriodSummary


class DataAggregator:
    """Produce LLM-digestible period summaries from TimescaleDB."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def summarize_period(self, period: str, days: int) -> PeriodSummary:
        """Summarize a lookback window into a structured :class:`PeriodSummary`.

        Computes:
          * Period averages, min, max, std dev per metric
          * Comparison vs rolling baseline (30d / 90d)
          * Day-of-week patterns
          * Best / worst days
        """
        raise NotImplementedError(
            "Aggregation deferred to Phase 1.5 — statistical engine wiring pending"
        )
