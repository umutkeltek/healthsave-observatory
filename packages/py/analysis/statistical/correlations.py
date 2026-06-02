"""Cross-metric correlation analysis — the n-of-1 hypothesis generator.

Two metrics that move together over a personal history are *candidates* for a
causal relationship worth testing with a controlled n-of-1 experiment (the
product's differentiating wedge). This module finds those candidates: it aligns
two daily series, gates on an overlap-aware sufficiency rule, and computes a
Spearman rank correlation, surfacing only the significant + non-trivial ones,
ranked strongest-first.

Spearman (rank) rather than Pearson: health relationships are typically
monotonic but not linear (more sleep helps recovery, with diminishing
returns), and ranks are robust to the outliers raw biometric streams are full
of.

Design boundaries, consistent with the rest of the analysis zone:

* **Pure core, no I/O.** :func:`correlate` and :func:`correlation_sufficiency`
  compute over in-memory ``{day: value}`` series. Fetching those series is the
  caller's job — :class:`CorrelationAnalyzer` takes an injected fetcher, so the
  module never imports SQLAlchemy and unit-tests against fakes.
* **The overlap gate lives here.** The ``correlation_analysis`` requirement
  (per-metric observations, overlapping days, overlap fraction) is exactly the
  one :func:`analysis.statistical.gates.check_sufficiency` refuses to evaluate
  from a single ``DataSummary`` — it needs *both* series. This is its home.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from ..types import Correlation, SufficiencyResult
from .gates import MINIMUM_DATA_REQUIREMENTS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# One day → one aggregate value for a single metric.
DailySeries = Mapping[date, float]

# Below this |rho|, a statistically-significant correlation is still too weak to
# act on (or to spend an experiment on). 0.3 is the conventional "moderate"
# floor. Tunable, like the recovery-score curves.
_MIN_ABS_COEFFICIENT = 0.3
_SIGNIFICANCE_P = 0.05


@dataclass(frozen=True)
class _Aligned:
    """Two series restricted to their shared days, in matching order."""

    a: list[float]
    b: list[float]


def _align(series_a: DailySeries, series_b: DailySeries) -> _Aligned:
    shared = sorted(set(series_a) & set(series_b))
    return _Aligned(a=[series_a[day] for day in shared], b=[series_b[day] for day in shared])


def correlation_sufficiency(series_a: DailySeries, series_b: DailySeries) -> SufficiencyResult:
    """Gate two daily series against the ``correlation_analysis`` requirement.

    Overlap fraction is the Jaccard index of the two day-sets
    (``|A ∩ B| / |A ∪ B|``) — a symmetric measure that penalizes a long series
    being compared against a short, barely-overlapping one, not just raw shared
    days.
    """
    requirement = MINIMUM_DATA_REQUIREMENTS["correlation_analysis"]
    min_per_metric = int(requirement["min_observations_per_metric"])
    min_overlap_days = int(requirement["min_overlapping_days"])
    min_overlap_pct = float(requirement["min_overlap_pct"])

    days_a, days_b = set(series_a), set(series_b)
    overlap = days_a & days_b
    union = days_a | days_b
    overlap_pct = (len(overlap) / len(union)) if union else 0.0

    missing: list[str] = []
    if len(days_a) < min_per_metric:
        missing.append(f"metric A {len(days_a)}/{min_per_metric} obs")
    if len(days_b) < min_per_metric:
        missing.append(f"metric B {len(days_b)}/{min_per_metric} obs")
    if len(overlap) < min_overlap_days:
        missing.append(f"{len(overlap)}/{min_overlap_days} overlapping days")
    if overlap_pct < min_overlap_pct:
        missing.append(f"overlap {overlap_pct:.0%}/{min_overlap_pct:.0%}")

    if missing:
        return SufficiencyResult(
            is_sufficient=False,
            missing_description="insufficient data for correlation: " + ", ".join(missing),
        )
    return SufficiencyResult(is_sufficient=True)


def _spearman(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Spearman rank correlation + two-sided p-value.

    Deferred import keeps module import cheap when correlation is disabled,
    while still using SciPy for the math (mirrors ``trends``).
    """
    import warnings

    from scipy.stats import spearmanr

    with warnings.catch_warnings():
        # A constant/near-constant series makes the coefficient undefined; we
        # detect that via the NaN result downstream, so SciPy's warning here is
        # redundant noise (and would spam logs on flat real-world metrics).
        warnings.simplefilter("ignore")
        result = spearmanr(xs, ys)
    return float(result.statistic), float(result.pvalue)


def correlate(
    metric_a: str,
    metric_b: str,
    series_a: DailySeries,
    series_b: DailySeries,
    *,
    period_days: int,
) -> Correlation | None:
    """Return a significant, non-trivial correlation between two series, or None.

    ``None`` covers every "nothing to report" path: insufficient/misaligned
    data, a degenerate (constant) series where the coefficient is undefined, a
    non-significant p-value, or a coefficient too weak to act on.
    """
    if not correlation_sufficiency(series_a, series_b).is_sufficient:
        return None

    aligned = _align(series_a, series_b)
    coefficient, p_value = _spearman(aligned.a, aligned.b)

    # A constant series has no rank variation → spearmanr returns NaN; that's
    # "cannot judge", never a real correlation.
    if math.isnan(coefficient):
        return None
    if p_value >= _SIGNIFICANCE_P or abs(coefficient) < _MIN_ABS_COEFFICIENT:
        return None

    return Correlation(
        metric_a=metric_a,
        metric_b=metric_b,
        coefficient=coefficient,
        method="spearman",
        period_days=period_days,
        p_value=p_value,
    )


class CorrelationAnalyzer:
    """Find meaningful cross-metric correlations over a rolling window.

    Data access is **injected** (``daily_series_fetcher``) rather than performed
    here, keeping the module out of the sealed storage zone and unit-testable
    without a database. The fetcher resolves ``(metric, days)`` to a
    ``{day: value}`` daily series; a pair whose metric has no data yields an
    empty series, fails the sufficiency gate, and is silently skipped.
    """

    # Real ontology metric_ids (see contracts/ontology.py), chosen for
    # physiological plausibility and because Apple Watch populates them:
    #   * HRV ↑ ↔ resting HR ↓ — the classic autonomic recovery signature.
    #   * resting HR ↔ respiratory rate — co-elevate under stress / illness.
    #   * steps ↔ active energy — activity coupling (a sanity correlation).
    #   * heart rate ↔ HRV — inverse autonomic tone.
    #   * active energy ↔ resting HR — training load vs recovery (same-day proxy).
    # Lagged pairs (yesterday's load → next-morning HRV/RHR) are deferred —
    # they need lag-alignment, which lands with the n-of-1 experiment engine.
    CORRELATION_PAIRS: list[tuple[str, str]] = [
        ("vital.hrv_sdnn", "vital.resting_heart_rate"),
        ("vital.resting_heart_rate", "vital.respiratory_rate"),
        ("activity.steps", "activity.active_energy"),
        ("vital.heart_rate", "vital.hrv_sdnn"),
        ("activity.active_energy", "vital.resting_heart_rate"),
    ]

    def __init__(
        self,
        daily_series_fetcher: Callable[[str, int], Awaitable[DailySeries]],
    ) -> None:
        self._fetch = daily_series_fetcher

    async def analyze(self, days: int = 30) -> list[Correlation]:
        """Correlate every configured pair; return findings strongest-first.

        Strongest-first ordering is deliberate: the top of the list is the best
        candidate to promote into an n-of-1 experiment.
        """
        cache: dict[str, DailySeries] = {}

        async def series_for(metric: str) -> DailySeries:
            if metric not in cache:
                cache[metric] = await self._fetch(metric, days)
            return cache[metric]

        found: list[Correlation] = []
        for metric_a, metric_b in self.CORRELATION_PAIRS:
            correlation = correlate(
                metric_a,
                metric_b,
                await series_for(metric_a),
                await series_for(metric_b),
                period_days=days,
            )
            if correlation is not None:
                found.append(correlation)

        found.sort(key=lambda c: abs(c.coefficient), reverse=True)
        return found
