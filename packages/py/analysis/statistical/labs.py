"""Lab reader math — pure, deterministic (Labs slice 1).

Brain-1 only: no DB, no HTTP, no LLM. The route maps stored rows into the plain
dataclasses below and renders what comes back; the narrator may later explain
the finished cards but never computes them.

Three readings of one blood marker:

* :func:`band_position` — one result against **the lab's own** printed range
  (never a population or "optimal" range).
* :func:`assess_marker` — the latest result against its band and against the
  person's own earlier results.
* :func:`lab_gaps` — two labs that measured the same marker close together:
  both values and the gap between them. Never a mean.

And one cross-match, :func:`cross_match_card`: the marker next to a related
wearable signal over the 30 days before each blood draw, as a
:class:`contracts.findings.FindingCard`. One wearable stream only (per-device
baseline rule); other streams are named in the limitations, never averaged in.
"Read together" is the only claim; nothing here states a cause.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from contracts.findings import (
    Coverage,
    Delta,
    EffectSize,
    FindingCard,
    NextQuestion,
    SourceRef,
    WindowRef,
)

BandStatus = Literal["below", "within", "above", "no_range", "censored", "unverified"]
Direction = Literal["up", "down", "flat"]
HistoryPosition = Literal["below_prior_range", "within_prior_range", "above_prior_range"]

GAP_MAX_DAYS = 14
WINDOW_DAYS = 30
# 21 of 30 days: the 70 % overlap floor the correlation gate already uses.
MIN_WINDOW_DAYS = 21
SPEARMAN_MIN_DRAWS = 4
EXACT_P_MAX_DRAWS = 8
FINDING_TYPE = "lab_wearable_cross_match"


@dataclass(frozen=True, slots=True)
class LabPoint:
    """One lab result as the engine sees it."""

    specimen_at: datetime
    value: float
    unit: str
    stream_id: str
    lab: str
    comparator: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def interpretable(self) -> bool:
        return "unit_unreconciled" not in self.quality_flags and math.isfinite(self.value)

    @property
    def censored(self) -> bool:
        return self.comparator is not None


@dataclass(frozen=True, slots=True)
class BandPosition:
    """Where a result sits against its own lab's range.

    ``fraction`` is 0 at the low bound and 1 at the high bound (outside the band
    it runs below 0 or above 1); ``None`` unless both bounds exist and the value
    is exact. ``distance`` is how far outside the nearest bound, in the result's
    unit; ``None`` when within, without a range, or censored.
    """

    status: BandStatus
    fraction: float | None = None
    distance: float | None = None


def band_position(point: LabPoint) -> BandPosition:
    if not point.interpretable:
        return BandPosition("unverified")
    low, high, value = point.reference_low, point.reference_high, point.value
    if low is None and high is None:
        return BandPosition("no_range")
    if point.censored:
        # "<0.5" means the true value is at most 0.5; ">90" at least 90.
        at_most = point.comparator in ("<", "<=")
        if (
            at_most
            and low is not None
            and (value < low or (value == low and point.comparator == "<"))
        ):
            return BandPosition("below")
        if (
            not at_most
            and high is not None
            and (value > high or (value == high and point.comparator == ">"))
        ):
            return BandPosition("above")
        if at_most and low is None and high is not None and value <= high:
            return BandPosition("within")
        if not at_most and high is None and low is not None and value >= low:
            return BandPosition("within")
        return BandPosition("censored")
    fraction = None
    if low is not None and high is not None and high > low:
        fraction = (value - low) / (high - low)
        if not math.isfinite(fraction):
            fraction = None
    if low is not None and value < low:
        distance = low - value
        return BandPosition("below", fraction, distance if math.isfinite(distance) else None)
    if high is not None and value > high:
        distance = value - high
        return BandPosition("above", fraction, distance if math.isfinite(distance) else None)
    return BandPosition("within", fraction)


@dataclass(frozen=True, slots=True)
class MarkerAssessment:
    latest: LabPoint
    latest_band: BandPosition
    previous: LabPoint | None
    change: float | None
    change_pct: float | None
    direction: Direction | None
    change_withheld: str | None
    previous_from_other_lab: bool
    prior_count: int
    prior_min: float | None
    prior_max: float | None
    versus_history: HistoryPosition | None
    outside_streak: int


def _ordered(points: Sequence[LabPoint]) -> list[LabPoint]:
    return sorted(points, key=lambda p: (p.specimen_at, p.lab, p.stream_id))


def _direction(change: float) -> Direction:
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"


def assess_marker(points: Sequence[LabPoint]) -> MarkerAssessment | None:
    """Latest result vs its band, vs the previous result, vs earlier results."""
    if not points:
        return None
    ordered = _ordered(points)
    latest = ordered[-1]
    prior = ordered[:-1]
    previous = prior[-1] if prior else None

    change = change_pct = None
    direction: Direction | None = None
    withheld: str | None = None
    if previous is None:
        withheld = "first result"
    elif not latest.interpretable or not previous.interpretable:
        withheld = "a result has an unverified unit or numeric value"
    elif latest.censored or previous.censored:
        withheld = "a result is a limit (< or >), not an exact value"
    elif latest.unit != previous.unit:
        withheld = "the two results use different units"
    else:
        change = latest.value - previous.value
        change_pct = None if previous.value == 0 else change / abs(previous.value) * 100
        if math.isfinite(change):
            direction = _direction(change)
            if change_pct is not None and not math.isfinite(change_pct):
                change_pct = None
        else:
            change = change_pct = None
            withheld = "the difference exceeds the supported numeric range"

    comparable = [
        p.value for p in prior if p.interpretable and not p.censored and p.unit == latest.unit
    ]
    prior_min = min(comparable) if comparable else None
    prior_max = max(comparable) if comparable else None
    versus: HistoryPosition | None = None
    if len(comparable) >= 2 and latest.interpretable and not latest.censored:
        assert prior_min is not None and prior_max is not None
        if latest.value < prior_min:
            versus = "below_prior_range"
        elif latest.value > prior_max:
            versus = "above_prior_range"
        else:
            versus = "within_prior_range"

    streak = 0
    for point in reversed(ordered):
        if band_position(point).status not in ("below", "above"):
            break
        streak += 1

    return MarkerAssessment(
        latest=latest,
        latest_band=band_position(latest),
        previous=previous,
        change=change,
        change_pct=change_pct,
        direction=direction,
        change_withheld=withheld,
        previous_from_other_lab=previous is not None and previous.stream_id != latest.stream_id,
        prior_count=len(prior),
        prior_min=prior_min,
        prior_max=prior_max,
        versus_history=versus,
        outside_streak=streak,
    )


@dataclass(frozen=True, slots=True)
class LabGap:
    """Two labs, one marker, close in time: both values, never their mean."""

    earlier: LabPoint
    later: LabPoint
    days_apart: float
    difference: float | None
    difference_pct: float | None
    earlier_band: BandPosition
    later_band: BandPosition

    @property
    def bands_disagree(self) -> bool:
        return self.earlier_band.status != self.later_band.status


def lab_gaps(points: Sequence[LabPoint], *, max_days: int = GAP_MAX_DAYS) -> list[LabGap]:
    ordered = _ordered(points)
    gaps: list[LabGap] = []
    for i, earlier in enumerate(ordered):
        for later in ordered[i + 1 :]:
            days = (later.specimen_at - earlier.specimen_at).total_seconds() / 86400
            if days > max_days:
                break
            if later.stream_id == earlier.stream_id:
                continue
            difference = difference_pct = None
            if (
                earlier.interpretable
                and later.interpretable
                and not (earlier.censored or later.censored)
                and earlier.unit == later.unit
            ):
                difference = later.value - earlier.value
                if earlier.value != 0:
                    difference_pct = difference / abs(earlier.value) * 100
                if not math.isfinite(difference):
                    difference = difference_pct = None
                elif difference_pct is not None and not math.isfinite(difference_pct):
                    difference_pct = None
            gaps.append(
                LabGap(
                    earlier=earlier,
                    later=later,
                    days_apart=round(days, 2),
                    difference=difference,
                    difference_pct=difference_pct,
                    earlier_band=band_position(earlier),
                    later_band=band_position(later),
                )
            )
    return gaps


# ──────────────────────────────────────────────────────────────────
# Cross-match with a wearable signal
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WearablePairing:
    """A marker and a wearable metric that are read together (not a cause)."""

    metric_id: str
    label: str
    unit: str


# Small and explicit. RMSSD is never substituted for SDNN.
PAIRINGS: dict[str, WearablePairing] = {
    "2276-4": WearablePairing("vital.resting_heart_rate", "resting heart rate", "bpm"),
    "718-7": WearablePairing("vital.hrv_sdnn", "heart rate variability (SDNN)", "ms"),
}


@dataclass(frozen=True, slots=True)
class WearableSample:
    at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class WindowSummary:
    """The wearable signal over the 30 days before one draw, on one stream."""

    draw: LabPoint
    start: datetime
    end: datetime
    days_with_data: int
    observation_count: int
    mean: float | None
    daily_means: tuple[float, ...] = field(default=())

    @property
    def sufficient(self) -> bool:
        return self.days_with_data >= MIN_WINDOW_DAYS


@dataclass(frozen=True, slots=True)
class CrossMatch:
    pairing: WearablePairing
    card: FindingCard | None
    reason: str | None
    stream_id: str | None
    windows: tuple[WindowSummary, ...] = ()


def _window(draw: LabPoint, samples: Sequence[WearableSample]) -> WindowSummary:
    end = draw.specimen_at
    start = end - min(timedelta(days=WINDOW_DAYS), end - datetime.min.replace(tzinfo=end.tzinfo))
    by_day: dict[date, list[float]] = defaultdict(list)
    count = 0
    for sample in samples:
        if start <= sample.at < end:
            by_day[sample.at.date()].append(sample.value)
            count += 1
    daily = tuple(statistics.fmean(values) for _, values in sorted(by_day.items()))
    return WindowSummary(
        draw=draw,
        start=start,
        end=end,
        days_with_data=len(daily),
        observation_count=count,
        mean=statistics.fmean(daily) if daily else None,
        daily_means=daily,
    )


def _pick_stream(
    latest: LabPoint, wearable: Mapping[str, Sequence[WearableSample]]
) -> tuple[str | None, WindowSummary | None]:
    best: tuple[int, int, str] | None = None
    best_window: WindowSummary | None = None
    for stream_id, samples in wearable.items():
        window = _window(latest, samples)
        key = (window.days_with_data, window.observation_count, stream_id)
        if window.days_with_data and (best is None or key > best):
            best, best_window = key, window
    return (best[2] if best else None), best_window


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def _then(previous: float, current: float, unit: str) -> str:
    """``58.1 then 61.4 bpm`` — earlier window first."""
    return f"{previous:.1f} then {current:.1f} {unit}"


def _day(moment: datetime) -> str:
    return moment.date().isoformat()


def _rho_label(rho: float) -> str:
    a = abs(rho)
    if a >= 0.7:
        return "strong"
    if a >= 0.5:
        return "moderate"
    return "weak"


def _d_label(d: float) -> str:
    a = abs(d)
    if a >= 0.8:
        return "large"
    if a >= 0.5:
        return "medium"
    if a >= 0.2:
        return "small"
    return "negligible"


def _cohens_d(earlier: Sequence[float], later: Sequence[float]) -> float | None:
    n1, n2 = len(earlier), len(later)
    if n1 < 2 or n2 < 2:
        return None
    pooled = ((n1 - 1) * statistics.variance(earlier) + (n2 - 1) * statistics.variance(later)) / (
        n1 + n2 - 2
    )
    if pooled <= 0:
        return None
    return (statistics.fmean(later) - statistics.fmean(earlier)) / math.sqrt(pooled)


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks (ties share the mean of their positions)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(sxx * syy)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """Spearman rho with a two-sided p-value.

    Blood draws are few, and the usual t-approximation is badly wrong there (it
    gives p = 0 for a perfect rank order of 4 draws, where the exact answer is
    2/24). Up to ``EXACT_P_MAX_DRAWS`` the p-value is exact: the share of all
    orderings whose |rho| is at least the observed one. Beyond that, scipy.
    """
    rx, ry = _ranks(xs), _ranks(ys)
    rho = _pearson(rx, ry)
    if rho is None:
        return None
    if len(xs) <= EXACT_P_MAX_DRAWS:
        observed = abs(rho) - 1e-12
        hits = total = 0
        for perm in itertools.permutations(ry):
            total += 1
            value = _pearson(rx, perm)
            if value is not None and abs(value) >= observed:
                hits += 1
        return rho, hits / total
    import warnings

    from scipy.stats import spearmanr

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = spearmanr(xs, ys)
    return rho, float(result.pvalue)


def cross_match_card(
    *,
    loinc: str,
    marker_name: str,
    points: Sequence[LabPoint],
    pairing: WearablePairing,
    wearable: Mapping[str, Sequence[WearableSample]],
    stream_labels: Mapping[str, str] | None = None,
    stream_plugins: Mapping[str, str] | None = None,
    lab_plugin_id: str = "labs-csv",
    marker_unit_label: str | None = None,
) -> CrossMatch:
    """The marker next to ``pairing``'s 30-day wearable baseline before each draw.

    Returns a card only when the window before the latest draw has at least
    ``MIN_WINDOW_DAYS`` days of data on one stream; otherwise ``reason`` says
    what is missing. Effect size: Spearman rho across draws once
    ``SPEARMAN_MIN_DRAWS`` draws have coverage, otherwise Cohen's d between the
    two most recent windows. Confidence stays ``low`` below 4 draws and is
    capped at ``medium`` below 8.

    The card's windows and ``delta`` describe the wearable signal (its change
    between the two most recent covered windows); the marker's own change is
    stated in the claim and lives in :func:`assess_marker`.
    """
    labels = stream_labels or {}
    plugins = stream_plugins or {}
    ordered = _ordered(points)
    if not ordered:
        return CrossMatch(pairing, None, "No results for this marker yet.", None)
    latest = ordered[-1]
    if not latest.interpretable:
        return CrossMatch(
            pairing,
            None,
            "The latest result has an unverified unit or numeric value and is not compared.",
            None,
        )
    if latest.censored:
        return CrossMatch(
            pairing,
            None,
            f"The latest result is a limit ({latest.comparator}{_fmt(latest.value)}), "
            "not an exact value, so it is not compared.",
            None,
        )

    stream_id, latest_window = _pick_stream(latest, wearable)
    if stream_id is None or latest_window is None:
        return CrossMatch(
            pairing,
            None,
            f"No {pairing.label} data in the {WINDOW_DAYS} days before the "
            f"{_day(latest.specimen_at)} draw.",
            None,
        )
    stream_label = labels.get(stream_id, "one wearable source")
    if not latest_window.sufficient:
        return CrossMatch(
            pairing,
            None,
            f"Only {latest_window.days_with_data} of {WINDOW_DAYS} days of {pairing.label} "
            f"({stream_label}) before the {_day(latest.specimen_at)} draw; "
            f"{MIN_WINDOW_DAYS} are needed.",
            stream_id,
            (latest_window,),
        )

    samples = wearable[stream_id]
    windows = tuple(
        _window(point, samples)
        for point in ordered
        if point.interpretable and not point.censored and point.unit == latest.unit
    )
    # Independent windows only: walking back from the latest draw, a draw whose
    # 30-day window overlaps the one already kept is left out, so no wearable
    # day is counted twice.
    paired: list[WindowSummary] = []
    overlapping = 0
    for window in reversed(windows):
        if not window.sufficient:
            continue
        if paired and window.end > paired[0].start:
            overlapping += 1
            continue
        paired.insert(0, window)
    k = len(paired)
    current = paired[-1]
    previous = paired[-2] if k >= 2 else None
    assert current.mean is not None

    unit_text = marker_unit_label or latest.unit
    if previous is not None:
        assert previous.mean is not None
        claim = (
            f"{marker_name} went from {_fmt(previous.draw.value)} to {_fmt(current.draw.value)} "
            f"{unit_text} ({_day(previous.draw.specimen_at)} to {_day(current.draw.specimen_at)}). "
            f"Over the {WINDOW_DAYS} days before each draw, your {pairing.label} averaged "
            f"{_then(previous.mean, current.mean, pairing.unit)} ({stream_label})."
        )
    else:
        claim = (
            f"{marker_name} was {_fmt(current.draw.value)} {unit_text} on "
            f"{_day(current.draw.specimen_at)}. Over the {WINDOW_DAYS} days before, your "
            f"{pairing.label} averaged {current.mean:.1f} {pairing.unit} ({stream_label}, "
            f"{current.days_with_data} days)."
        )

    delta = None
    effect = None
    if previous is not None:
        assert previous.mean is not None
        change = current.mean - previous.mean
        delta = Delta(
            absolute=round(change, 3),
            pct=None if previous.mean == 0 else round(change / abs(previous.mean) * 100, 2),
            unit=pairing.unit,
            direction=_direction(round(change, 9)),
        )
    if k >= SPEARMAN_MIN_DRAWS:
        rho_p = _spearman([w.draw.value for w in paired], [w.mean or 0.0 for w in paired])
        if rho_p is not None:
            rho, p_value = rho_p
            effect = EffectSize(
                value=round(rho, 3),
                kind="spearman_rho",
                label=f"{_rho_label(rho)}, across {k} draws",
                p_value=round(p_value, 4),
            )
    elif previous is not None:
        d = _cohens_d(previous.daily_means, current.daily_means)
        if d is not None:
            effect = EffectSize(
                value=round(d, 3),
                kind="cohens_d",
                label=f"{_d_label(d)} shift in {pairing.label} between the two windows",
            )

    limitations = [
        "Exploratory comparison; p-values are not calibrated confidence or medical evidence. "
        "Repeated testing and serial dependence are not accounted for.",
        "Read together, not cause and effect: two measurements are placed side by side.",
        f"Blood draws are sparse: {k} of {len(ordered)} have their own {WINDOW_DAYS}-day "
        f"window with {MIN_WINDOW_DAYS}+ days of {pairing.label}.",
        f"A draw is one moment; the {pairing.label} value is the average of the "
        f"{WINDOW_DAYS} days before it.",
    ]
    others = sorted(
        labels.get(other, "another source")
        for other, other_samples in wearable.items()
        if other != stream_id and _window(latest, other_samples).days_with_data
    )
    if others:
        limitations.append(
            f"Only {stream_label} was used. {', '.join(others)} also recorded "
            f"{pairing.label}; it was not averaged in."
        )
    if overlapping:
        limitations.append(
            f"{overlapping} draw(s) less than {WINDOW_DAYS} days before a later one were left "
            "out, so no wearable day is counted twice."
        )
    if len({w.draw.stream_id for w in paired}) > 1:
        limitations.append(
            "These draws come from more than one lab; each lab has its own range and method."
        )

    card = FindingCard(
        claim=claim,
        metric=f"loinc:{loinc}",
        finding_type=FINDING_TYPE,
        current_window=WindowRef(
            label=f"{WINDOW_DAYS} days before the {_day(current.draw.specimen_at)} draw",
            start=current.start,
            end=current.end,
            n=current.days_with_data,
        ),
        baseline_window=(
            WindowRef(
                label=f"{WINDOW_DAYS} days before the {_day(previous.draw.specimen_at)} draw",
                start=previous.start,
                end=previous.end,
                n=previous.days_with_data,
            )
            if previous is not None
            else None
        ),
        delta=delta,
        effect_size=effect,
        coverage=Coverage(
            is_sufficient=True,
            observation_count=current.observation_count,
            days_with_data=current.days_with_data,
            note=(
                f"{current.days_with_data} of {WINDOW_DAYS} days before the latest draw, on one "
                f"source ({MIN_WINDOW_DAYS} needed); {k} of {len(ordered)} draws have their "
                "own window with coverage."
            ),
        ),
        sources=[
            SourceRef(
                source_plugin_id=lab_plugin_id,
                label=", ".join(sorted({w.draw.lab for w in paired})),
            ),
            SourceRef(source_plugin_id=plugins.get(stream_id), label=stream_label),
        ],
        confidence=None,
        limitations=limitations,
        next_question=NextQuestion(
            prose=(
                f"Add your next {marker_name} result to see whether it and your "
                f"{pairing.label} keep moving together."
            )
        ),
    )
    return CrossMatch(pairing, card, None, stream_id, windows)


__all__ = [
    "GAP_MAX_DAYS",
    "MIN_WINDOW_DAYS",
    "PAIRINGS",
    "WINDOW_DAYS",
    "BandPosition",
    "CrossMatch",
    "LabGap",
    "LabPoint",
    "MarkerAssessment",
    "WearablePairing",
    "WearableSample",
    "WindowSummary",
    "assess_marker",
    "band_position",
    "cross_match_card",
    "lab_gaps",
]
