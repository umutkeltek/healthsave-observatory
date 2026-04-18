"""Data-sufficiency gates — block analysis when there isn't enough data.

See ``docs/HEALTH_DOMAIN_SUPPLEMENT.md`` §5.4. Constants are duplicated
here so the gate logic is inspectable without reading the supplement.
"""

from ..types import DataSummary, SufficiencyResult

MINIMUM_DATA_REQUIREMENTS: dict[str, dict[str, float]] = {
    "anomaly_detection": {
        "min_observations": 14,
        "min_days": 7,
    },
    "trend_analysis": {
        "min_observations": 21,
        "min_days": 14,
    },
    "correlation_analysis": {
        "min_observations_per_metric": 21,
        "min_overlapping_days": 14,
        "min_overlap_pct": 0.70,
    },
    "recovery_score": {
        "min_overnight_sessions": 7,
    },
    "weekly_summary": {
        "min_days_in_week": 5,
    },
}


def check_sufficiency(analysis_type: str, available_data: DataSummary) -> SufficiencyResult:
    """Return whether the available data satisfies the requirement."""
    raise NotImplementedError(
        "Sufficiency gating deferred to Phase 1.5 — statistical engine wiring pending"
    )
