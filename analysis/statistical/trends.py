"""Trend analysis - linear regression over daily aggregates."""

from ..types import Trend


class TrendAnalyzer:
    """Detect multi-day/multi-week trends via linear regression."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def analyze(self, metric: str, days: int = 30) -> Trend | None:
        """Return a significant trend for ``metric`` over the window, or None.

        Algorithm outline (to implement in Phase 1.5):
          1. Fetch daily aggregates for the window
          2. Fit linear regression (``scipy.stats.linregress`` - Phase 1.5)
          3. Return a :class:`Trend` if the slope is significant (p < 0.05)
          4. Include magnitude, direction, and confidence interval
        """
        raise NotImplementedError(
            "Trend analysis deferred to Phase 1.5 - scipy dep will land with it"
        )
