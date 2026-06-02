"""ABAB n-of-1 experiment statistics — the controlled + observational engine.

Pure Brain-1: given an outcome metric's daily series and an experiment's phase
calendar, decide whether the behavioral *lever* actually moved the *outcome*.
No DB, no HTTP, no LLM — every function takes plain ``{date: value}`` maps and
returns frozen dataclasses, so it unit-tests without a database or the ontology.

Two analyses, matching the product's two reads:

* :func:`analyze_abab` — the *controlled* result. Days are labelled A (baseline)
  or B (intervention) by the experiment's :func:`build_phase_calendar`; pool the
  outcome by label and report the mean difference, effect size, and a
  block-level randomization (permutation) p-value. The p-value is reported only
  when there are enough blocks to make it meaningful; otherwise the result is
  honestly flagged ``descriptive_only``.
* :func:`analyze_median_split` — the *retrospective* read. Existing history is
  split at the lever's median into high- vs low-lever days and the outcome
  compared. Observational (association, not causation) — labelled as such.

Adherence (:func:`adherence_from_lever`) reuses the controlled analysis on the
*lever itself*: a real intervention shows the lever separating across A/B
blocks. A failed manipulation is surfaced, not hidden.

The statistics are deliberately honest-but-light — the roadmap's stated #1 risk
is over-rigor before behavioural gravity, so there is no Bayesian or
mixed-effects modelling: descriptive stats + effect size + an exact permutation
test when (and only when) the block count supports inference.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations

from .experiment_readiness import _short  # human-readable metric tail (shared)

DEFAULT_DESIGN = "ABAB"
DEFAULT_BLOCK_DAYS = 7

# A block-level permutation test over a 4-block ABAB design has only C(4,2)=6
# distinct label assignments — the smallest two-sided p it can produce is
# ~1/6≈0.17, too coarse to call "significant". We only report a p-value when the
# number of distinct arrangements clears this floor; below it the result is
# descriptive_only. 10 arrangements ≈ 5 informative blocks (C(5,2)=10).
_MIN_PERMUTATIONS_FOR_INFERENCE = 10

# Need at least this many days per phase before A/B means mean anything.
_MIN_DAYS_PER_PHASE = 2
# Minimum overlapping days for the observational median split to be worth running.
_MIN_OVERLAP_DAYS = 6

# Effect-size thresholds (|Cohen's d|) for the adherence read on the lever.
_ADHERENCE_STRONG_D = 0.8
_ADHERENCE_WEAK_D = 0.3

# Outcome direction is "flat" when |diff| is a rounding whisker.
_FLAT_EPS = 1e-9


@dataclass(frozen=True)
class Phase:
    """One block of an experiment calendar: a contiguous ``[start, end)`` day-range."""

    label: str  # "A" (baseline) | "B" (intervention)
    index: int  # 0-based block number
    start: date
    end: date  # exclusive

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end


@dataclass(frozen=True)
class ExperimentProgress:
    """Where an experiment sits in its run, computed against a reference day."""

    current_phase: str | None  # "A" | "B" | None (before start / after end)
    day_index: int  # elapsed days within the window, clamped to [0, total_days]
    total_days: int
    days_remaining: int
    is_complete: bool
    pct: float  # 0..1


@dataclass(frozen=True)
class PhaseComparison:
    """An A-vs-B comparison of one metric — the core result shape."""

    status: str  # "ok" | "insufficient"
    n_a: int
    n_b: int
    mean_a: float | None
    mean_b: float | None
    diff: float | None  # mean_b - mean_a
    pooled_sd: float | None
    effect_size: float | None  # Cohen's d (diff / pooled_sd)
    direction: str  # "increase" | "decrease" | "flat" | "unknown"
    p_value: float | None
    inference: str  # randomization_test | descriptive_only | observational | insufficient
    n_blocks_used: int
    caveat: str


@dataclass(frozen=True)
class AdherenceCheck:
    """Did the lever actually move across A/B blocks (was the experiment run)."""

    status: str  # "strong" | "weak" | "none" | "insufficient"
    lever_diff: float | None
    lever_effect_size: float | None
    note: str


# ──────────────────────────────────────────────────────────────────────
#  Phase calendar
# ──────────────────────────────────────────────────────────────────────


def build_phase_calendar(
    start_date: date,
    block_days: int = DEFAULT_BLOCK_DAYS,
    design: str = DEFAULT_DESIGN,
) -> list[Phase]:
    """Lay out one :class:`Phase` per character of ``design`` (e.g. ``"ABAB"``).

    Each block is ``block_days`` consecutive days; blocks abut with no gap, so
    the calendar spans ``len(design) * block_days`` days from ``start_date``.
    """
    design = design.upper()
    if block_days < 1:
        raise ValueError("block_days must be >= 1")
    if not design or any(c not in ("A", "B") for c in design):
        raise ValueError("design must be a non-empty string of 'A'/'B'")

    phases: list[Phase] = []
    cursor = start_date
    for index, label in enumerate(design):
        nxt = cursor + timedelta(days=block_days)
        phases.append(Phase(label=label, index=index, start=cursor, end=nxt))
        cursor = nxt
    return phases


def phase_label_for(calendar: list[Phase], day: date) -> str | None:
    """The A/B label of the block containing ``day``, or None if outside the window."""
    for phase in calendar:
        if phase.contains(day):
            return phase.label
    return None


def experiment_window(calendar: list[Phase]) -> tuple[date, date]:
    """Overall ``[start, end)`` of a calendar (end exclusive)."""
    return calendar[0].start, calendar[-1].end


def progress(calendar: list[Phase], today: date) -> ExperimentProgress:
    """Elapsed / remaining days and the current phase, relative to ``today``."""
    start, end = experiment_window(calendar)
    total_days = (end - start).days

    if today < start:
        return ExperimentProgress(None, 0, total_days, total_days, False, 0.0)
    if today >= end:
        return ExperimentProgress(None, total_days, total_days, 0, True, 1.0)

    day_index = (today - start).days
    return ExperimentProgress(
        current_phase=phase_label_for(calendar, today),
        day_index=day_index,
        total_days=total_days,
        days_remaining=total_days - day_index,
        is_complete=False,
        pct=(day_index / total_days) if total_days else 0.0,
    )


# ──────────────────────────────────────────────────────────────────────
#  Core comparison helpers
# ──────────────────────────────────────────────────────────────────────


def _direction(diff: float) -> str:
    if diff > _FLAT_EPS:
        return "increase"
    if diff < -_FLAT_EPS:
        return "decrease"
    return "flat"


def _pooled_sd(a: list[float], b: list[float]) -> float | None:
    """Pooled sample SD (ddof=1). None when the pooled dof is non-positive."""
    na, nb = len(a), len(b)
    if na + nb - 2 <= 0:
        return None
    var_a = statistics.variance(a) if na >= 2 else 0.0
    var_b = statistics.variance(b) if nb >= 2 else 0.0
    pooled_var = ((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2)
    return math.sqrt(pooled_var) if pooled_var > 0 else 0.0


def _effect_size(diff: float, pooled_sd: float | None) -> float:
    """Cohen's d; 0.0 when the pooled SD is zero/undefined (no spread to scale by)."""
    return diff / pooled_sd if pooled_sd and pooled_sd > 0 else 0.0


def _block_stat(means: list[float], is_b: list[bool]) -> float:
    """Test statistic for the permutation test: mean(B block-means) − mean(A block-means)."""
    b = [m for m, flag in zip(means, is_b, strict=True) if flag]
    a = [m for m, flag in zip(means, is_b, strict=True) if not flag]
    return statistics.fmean(b) - statistics.fmean(a)


def _block_permutation_p(
    per_block: dict[int, list[float]],
    block_label: dict[int, str],
    blocks_with_data: list[int],
) -> tuple[float | None, str]:
    """Two-sided exact permutation p over block-label assignments.

    Treats each *block* (not each day) as the exchangeable unit — the honest unit
    for autocorrelated daily measurements. Enumerates every way to assign the
    observed number of A/B labels across the blocks-with-data and counts the
    fraction whose ``|statistic| >= |observed|``. The observed assignment is one
    of the enumerated arrangements, so ``p >= 1/distinct`` always. Returns
    ``(None, "descriptive_only")`` when there are too few distinct arrangements
    to produce a meaningful p-value.
    """
    means = [statistics.fmean(per_block[i]) for i in blocks_with_data]
    labels = [block_label[i] for i in blocks_with_data]
    n = len(blocks_with_data)
    n_b = labels.count("B")

    if n_b == 0 or n_b == n:  # only one phase has any block-level data
        return None, "descriptive_only"

    distinct = math.comb(n, n_b)
    if distinct < _MIN_PERMUTATIONS_FOR_INFERENCE:
        return None, "descriptive_only"

    observed = abs(_block_stat(means, [lab == "B" for lab in labels]))
    count = 0
    for b_positions in combinations(range(n), n_b):
        is_b = [False] * n
        for pos in b_positions:
            is_b[pos] = True
        if abs(_block_stat(means, is_b)) >= observed - 1e-12:
            count += 1
    return count / distinct, "randomization_test"


def _insufficient(
    n_a: int, n_b: int, a: list[float], b: list[float], caveat: str
) -> PhaseComparison:
    return PhaseComparison(
        status="insufficient",
        n_a=n_a,
        n_b=n_b,
        mean_a=statistics.fmean(a) if a else None,
        mean_b=statistics.fmean(b) if b else None,
        diff=None,
        pooled_sd=None,
        effect_size=None,
        direction="unknown",
        p_value=None,
        inference="insufficient",
        n_blocks_used=0,
        caveat=caveat,
    )


# ──────────────────────────────────────────────────────────────────────
#  Controlled ABAB
# ──────────────────────────────────────────────────────────────────────


def analyze_abab(values_by_day: dict[date, float], calendar: list[Phase]) -> PhaseComparison:
    """Controlled A-vs-B comparison of a metric over an experiment's phase calendar."""
    a_vals: list[float] = []
    b_vals: list[float] = []
    per_block: dict[int, list[float]] = defaultdict(list)
    block_label: dict[int, str] = {}

    for day, value in values_by_day.items():
        for phase in calendar:
            if phase.contains(day):
                per_block[phase.index].append(value)
                block_label[phase.index] = phase.label
                (a_vals if phase.label == "A" else b_vals).append(value)
                break

    n_a, n_b = len(a_vals), len(b_vals)
    blocks_with_data = sorted(per_block)

    if n_a < _MIN_DAYS_PER_PHASE or n_b < _MIN_DAYS_PER_PHASE:
        return _insufficient(
            n_a,
            n_b,
            a_vals,
            b_vals,
            "Not enough data in both phases yet — need at least "
            f"{_MIN_DAYS_PER_PHASE} days each of baseline (A) and intervention (B).",
        )

    mean_a = statistics.fmean(a_vals)
    mean_b = statistics.fmean(b_vals)
    diff = mean_b - mean_a
    pooled = _pooled_sd(a_vals, b_vals)
    p_value, inference = _block_permutation_p(per_block, block_label, blocks_with_data)

    caveat = (
        "n-of-1 daily measurements are autocorrelated; the randomization test "
        "treats each block as the unit to account for that. "
    )
    if inference == "descriptive_only":
        caveat += (
            f"Only {len(blocks_with_data)} block(s) carry data — too few for a "
            "trustworthy p-value, so this is descriptive (effect size) only. "
            "Run more A/B blocks for a significance test."
        )

    return PhaseComparison(
        status="ok",
        n_a=n_a,
        n_b=n_b,
        mean_a=mean_a,
        mean_b=mean_b,
        diff=diff,
        pooled_sd=pooled,
        effect_size=_effect_size(diff, pooled),
        direction=_direction(diff),
        p_value=p_value,
        inference=inference,
        n_blocks_used=len(blocks_with_data),
        caveat=caveat,
    )


def adherence_from_lever(lever_by_day: dict[date, float], calendar: list[Phase]) -> AdherenceCheck:
    """Did the lever separate across A/B blocks — i.e., was the intervention carried out.

    Reuses :func:`analyze_abab` on the *lever* itself. We expect the lever to be
    higher during B (intervention) blocks; a strong positive separation confirms
    the manipulation, a flat/negative one says it likely didn't happen.
    """
    pc = analyze_abab(lever_by_day, calendar)
    if pc.status != "ok" or pc.diff is None or pc.effect_size is None:
        return AdherenceCheck(
            status="insufficient",
            lever_diff=pc.diff,
            lever_effect_size=pc.effect_size,
            note="Not enough lever data across blocks to confirm the intervention happened.",
        )

    d = pc.effect_size
    # Cohen's d is undefined (reported as 0.0) when there's no within-phase
    # spread — but a clean A/B gap with zero noise is *perfect* separation, not
    # "no effect". Treat zero pooled variance as a maximal separation so a
    # flawless manipulation isn't misread as non-adherence.
    perfect = pc.pooled_sd == 0.0 and pc.direction != "flat"

    if pc.direction == "increase" and (perfect or d >= _ADHERENCE_STRONG_D):
        status = "strong"
        note = (
            "The lever clearly separated between baseline and intervention blocks "
            "— the intervention was carried out."
        )
    elif pc.direction == "increase" and d >= _ADHERENCE_WEAK_D:
        status = "weak"
        note = (
            "The lever separated only weakly between blocks — the intervention may "
            "have been inconsistent, so read the result with caution."
        )
    elif pc.direction == "decrease":
        status = "none"
        note = (
            "The lever moved the wrong way (lower during intervention blocks) — the "
            "protocol likely wasn't followed."
        )
    else:
        status = "none"
        note = (
            "The lever barely differed between baseline and intervention blocks — the "
            "intervention doesn't appear to have happened."
        )
    return AdherenceCheck(status=status, lever_diff=pc.diff, lever_effect_size=d, note=note)


# ──────────────────────────────────────────────────────────────────────
#  Observational (retrospective) median split
# ──────────────────────────────────────────────────────────────────────


def _mann_whitney_p(a: list[float], b: list[float]) -> float | None:
    """Two-sided Mann-Whitney U p-value (deferred SciPy import, like correlations).

    Returns None when the test is undefined (e.g. every value identical), which
    SciPy raises ``ValueError`` for — an honest "no test possible", not a crash.
    """
    if not a or not b:
        return None
    from scipy.stats import mannwhitneyu

    try:
        return float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
    except ValueError:
        return None


def analyze_median_split(
    outcome_by_day: dict[date, float],
    lever_by_day: dict[date, float],
) -> PhaseComparison:
    """Observational A/B: split shared history at the lever's median, compare the outcome.

    A balanced rank split (low-lever half vs high-lever half; the middle day is
    dropped on an odd count) so ties in the lever can't empty a group. This is
    the instant retrospective read from existing data — clearly observational,
    not a controlled intervention.
    """
    shared = sorted(set(outcome_by_day) & set(lever_by_day))
    n = len(shared)
    if n < _MIN_OVERLAP_DAYS:
        return _insufficient(
            0,
            0,
            [],
            [],
            "Not enough overlapping history to compare high- vs low-lever days yet "
            f"({n}/{_MIN_OVERLAP_DAYS} days).",
        )

    order = sorted(shared, key=lambda d: lever_by_day[d])
    half = n // 2
    a_vals = [outcome_by_day[d] for d in order[:half]]  # low-lever days (baseline-like)
    b_vals = [outcome_by_day[d] for d in order[n - half :]]  # high-lever days (intervention-like)

    mean_a = statistics.fmean(a_vals)
    mean_b = statistics.fmean(b_vals)
    diff = mean_b - mean_a
    pooled = _pooled_sd(a_vals, b_vals)

    return PhaseComparison(
        status="ok",
        n_a=len(a_vals),
        n_b=len(b_vals),
        mean_a=mean_a,
        mean_b=mean_b,
        diff=diff,
        pooled_sd=pooled,
        effect_size=_effect_size(diff, pooled),
        direction=_direction(diff),
        p_value=_mann_whitney_p(a_vals, b_vals),
        inference="observational",
        n_blocks_used=0,
        caveat=(
            "Observational: days are split by your own lever level over existing "
            "history, not a controlled intervention — this shows association, not "
            "causation. Confounders (sleep, stress, day of week) are not controlled."
        ),
    )


# ──────────────────────────────────────────────────────────────────────
#  Plain-language summary
# ──────────────────────────────────────────────────────────────────────


def summarize(pc: PhaseComparison, *, outcome_short: str, period_phrase: str) -> str:
    """A polarity-agnostic one-line summary of a :class:`PhaseComparison`.

    ``period_phrase`` describes the "B" side in words — e.g. ``"intervention
    blocks"`` (controlled) or ``"high-steps days"`` (observational).
    """
    if pc.status != "ok" or pc.diff is None or pc.effect_size is None:
        return f"Not enough data yet to measure {outcome_short}."
    if pc.direction == "flat":
        return (
            f"{outcome_short.capitalize()} was about the same during {period_phrase} "
            f"(d={pc.effect_size:.2f})."
        )
    word = "higher" if pc.direction == "increase" else "lower"
    return (
        f"{outcome_short.capitalize()} was {abs(pc.diff):.2f} {word} during "
        f"{period_phrase} (d={pc.effect_size:.2f})."
    )


__all__ = [
    "DEFAULT_BLOCK_DAYS",
    "DEFAULT_DESIGN",
    "Phase",
    "ExperimentProgress",
    "PhaseComparison",
    "AdherenceCheck",
    "build_phase_calendar",
    "phase_label_for",
    "experiment_window",
    "progress",
    "analyze_abab",
    "adherence_from_lever",
    "analyze_median_split",
    "summarize",
    "_short",
]
