"""Cross-metric correlation analysis."""

from ..types import Correlation


class CorrelationAnalyzer:
    """Find meaningful cross-metric correlations over a rolling window."""

    CORRELATION_PAIRS: list[tuple[str, str]] = [
        ("sleep_efficiency", "resting_hr"),
        ("hrv", "sleep_deep_pct"),
        ("alcohol_logged", "hrv_next_morning"),
        ("steps", "sleep_quality"),
        ("active_calories", "resting_hr_next"),
    ]

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def analyze(self, days: int = 30) -> list[Correlation]:
        """Compute Spearman rank correlation for the configured metric pairs."""
        raise NotImplementedError(
            "Correlation analysis deferred to Phase 1.5 - scipy dep will land with it"
        )
