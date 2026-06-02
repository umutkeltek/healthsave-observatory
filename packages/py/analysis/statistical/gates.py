"""Data-sufficiency gates - block analysis when there isn't enough data.

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


# Requirement keys this gate can evaluate from a single DataSummary, which
# models only "how many observations" and "over how many distinct days".
_OBSERVATION_KEY = "min_observations"
_DAY_KEYS = ("min_days", "min_days_in_week")
_SUPPORTED_KEYS = frozenset({_OBSERVATION_KEY, *_DAY_KEYS})


def check_sufficiency(analysis_type: str, available_data: DataSummary) -> SufficiencyResult:
    """Return whether ``available_data`` satisfies the requirement.

    Evaluable from a plain :class:`DataSummary` only when the requirement is
    expressed as total observations + distinct days (``anomaly_detection``,
    ``trend_analysis``, ``weekly_summary``). ``correlation_analysis`` and
    ``recovery_score`` carry cross-metric overlap / per-session inputs a
    single ``DataSummary`` doesn't model — calling this with those raises
    ``ValueError`` rather than letting an unmet gate silently pass. An unknown
    ``analysis_type`` is also a ``ValueError``.
    """
    try:
        requirement = MINIMUM_DATA_REQUIREMENTS[analysis_type]
    except KeyError:
        raise ValueError(f"unknown analysis_type: {analysis_type!r}") from None

    unsupported = set(requirement) - _SUPPORTED_KEYS
    if unsupported:
        raise ValueError(
            f"{analysis_type!r} needs a specialized gate; "
            f"{sorted(unsupported)} cannot be evaluated from a DataSummary"
        )

    min_observations = int(requirement.get(_OBSERVATION_KEY, 0))
    min_days = next((int(requirement[key]) for key in _DAY_KEYS if key in requirement), 0)

    observations_short = available_data.observation_count < min_observations
    days_short = available_data.days_with_data < min_days
    if not observations_short and not days_short:
        return SufficiencyResult(is_sufficient=True)

    missing: list[str] = []
    if observations_short:
        missing.append(f"{available_data.observation_count}/{min_observations} observations")
    if days_short:
        missing.append(f"{available_data.days_with_data}/{min_days} days with data")

    # Estimate calendar days remaining only when days are the binding
    # constraint — one new day of data per calendar day. An observation
    # shortfall alone gives no estimate (the per-day sampling rate is unknown).
    days_until = (min_days - available_data.days_with_data) if days_short else None

    return SufficiencyResult(
        is_sufficient=False,
        missing_description="insufficient data: " + ", ".join(missing),
        days_until_sufficient=days_until,
    )
