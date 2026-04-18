"""Anomaly detection — z-score and % deviation from personal baseline."""

from ..types import Anomaly


class AnomalyDetector:
    """Detect statistically significant deviations from baseline."""

    def __init__(self, session_factory, config) -> None:
        self.session_factory = session_factory
        self.config = config

    async def detect(self, lookback_days: int = 7) -> list[Anomaly]:
        """Return all anomalies detected in the lookback window.

        Algorithm outline (to implement in Phase 1.5):
          1. Compute rolling baseline (30-day mean + stddev) per metric
          2. Flag values more than 2 stddev from baseline
          3. Context-filter: exclude workout periods from HR anomalies
          4. Cluster nearby anomalies into events
          5. Suppress anomalies during cold-start window (see gates.py)
        """
        raise NotImplementedError(
            "Anomaly detection deferred to Phase 1.5 — statistical engine wiring pending"
        )
