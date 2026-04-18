"""Rolling baseline computation — per-user, per-device, per-metric."""


class BaselineTracker:
    """Compute and cache rolling 30/90-day baselines per device + metric.

    Baselines are computed PER DEVICE — switching from Apple Watch to
    Whoop triggers a new baseline (see supplement §5.5). Cross-device
    correlation requires an explicit calibration period.
    """

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def baseline_for(
        self, metric: str, device_id: int, days: int = 30
    ) -> dict[str, float] | None:
        """Return ``{mean, stddev, p10, p50, p90}`` for the window, or None."""
        raise NotImplementedError(
            "Baseline computation deferred to Phase 1.5 — statistical engine wiring pending"
        )
