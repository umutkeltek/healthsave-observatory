"""Unit tests for the pure ABAB experiment statistics.

No DB, no ontology — every function takes plain ``{date: value}`` maps. Covers
calendar construction, progress, the controlled ABAB analysis (including the
descriptive_only vs randomization_test threshold), the observational median
split, adherence inference, and the plain-language summary.
"""

from __future__ import annotations

from datetime import date

import pytest
from analysis.statistical.experiments import (
    adherence_from_lever,
    analyze_abab,
    analyze_median_split,
    build_phase_calendar,
    experiment_window,
    phase_label_for,
    progress,
    summarize,
)

START = date(2026, 1, 1)


# ── calendar ────────────────────────────────────────────────────────────


def test_build_phase_calendar_lays_out_abutting_blocks():
    cal = build_phase_calendar(START, block_days=7, design="ABAB")
    assert [p.label for p in cal] == ["A", "B", "A", "B"]
    assert [p.index for p in cal] == [0, 1, 2, 3]
    assert cal[0].start == START and cal[0].end == date(2026, 1, 8)
    assert cal[1].start == date(2026, 1, 8)  # abuts, no gap
    start, end = experiment_window(cal)
    assert start == START and end == date(2026, 1, 29)  # 4 * 7 = 28 days


def test_phase_label_for_inside_and_outside():
    cal = build_phase_calendar(START, block_days=2, design="ABAB")
    assert phase_label_for(cal, date(2026, 1, 1)) == "A"
    assert phase_label_for(cal, date(2026, 1, 3)) == "B"
    assert phase_label_for(cal, date(2026, 1, 5)) == "A"
    assert phase_label_for(cal, date(2025, 12, 31)) is None  # before
    assert phase_label_for(cal, date(2026, 1, 9)) is None  # after end (exclusive)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"block_days": 0, "design": "ABAB"},
        {"block_days": 7, "design": ""},
        {"block_days": 7, "design": "AC"},
    ],
)
def test_build_phase_calendar_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        build_phase_calendar(START, **kwargs)


# ── progress ────────────────────────────────────────────────────────────


def test_progress_before_during_and_after():
    cal = build_phase_calendar(START, block_days=7, design="ABAB")  # 28 days

    before = progress(cal, date(2025, 12, 25))
    assert before.current_phase is None and before.day_index == 0 and not before.is_complete

    mid = progress(cal, date(2026, 1, 10))  # day 9 → block 1 (B)
    assert mid.current_phase == "B"
    assert mid.day_index == 9 and mid.total_days == 28
    assert mid.days_remaining == 19 and not mid.is_complete
    assert 0 < mid.pct < 1

    done = progress(cal, date(2026, 2, 1))
    assert done.is_complete and done.days_remaining == 0 and done.pct == 1.0


# ── controlled ABAB ───────────────────────────────────────────────────────


def _abab_series(a_value: float, b_value: float, *, block_days: int, design: str):
    """Constant-per-phase daily series over the calendar (A=a_value, B=b_value)."""
    cal = build_phase_calendar(START, block_days=block_days, design=design)
    values: dict[date, float] = {}
    for phase in cal:
        day = phase.start
        while day < phase.end:
            values[day] = a_value if phase.label == "A" else b_value
            day = day.fromordinal(day.toordinal() + 1)
    return values, cal


def test_analyze_abab_insufficient_when_a_phase_too_short():
    cal = build_phase_calendar(START, block_days=1, design="AB")  # 1 day each phase
    values = {START: 50.0, date(2026, 1, 2): 60.0}
    result = analyze_abab(values, cal)
    assert result.status == "insufficient"
    assert result.inference == "insufficient" and result.p_value is None


def test_analyze_abab_four_blocks_is_descriptive_only():
    # B clearly higher, but only C(4,2)=6 arrangements → too few to infer.
    values, cal = _abab_series(50.0, 60.0, block_days=2, design="ABAB")
    # add spread so pooled SD > 0
    values[START] = 49.0
    result = analyze_abab(values, cal)
    assert result.status == "ok"
    assert result.direction == "increase" and result.diff > 0
    assert result.n_blocks_used == 4
    assert result.inference == "descriptive_only" and result.p_value is None
    assert result.effect_size is not None
    assert "descriptive" in result.caveat.lower()


def test_analyze_abab_six_blocks_runs_randomization_test():
    # 6 perfectly-separated blocks (3 A=50, 3 B=60): C(6,3)=20 arrangements,
    # two extremes hit |stat|=10 → exact two-sided p = 2/20 = 0.1.
    values, cal = _abab_series(50.0, 60.0, block_days=2, design="ABABAB")
    result = analyze_abab(values, cal)
    assert result.status == "ok" and result.n_blocks_used == 6
    assert result.inference == "randomization_test"
    assert result.p_value == pytest.approx(0.1)
    assert result.direction == "increase"


def test_analyze_abab_decrease_direction():
    values, cal = _abab_series(60.0, 50.0, block_days=2, design="ABAB")
    values[START] = 61.0  # spread
    result = analyze_abab(values, cal)
    assert result.direction == "decrease" and result.diff < 0


# ── observational median split ────────────────────────────────────────────


def test_analyze_median_split_observational():
    # lever rises across 10 days; outcome falls with it → high-lever days lower.
    lever = {date(2026, 1, d): float(d) for d in range(1, 11)}
    outcome = {date(2026, 1, d): 100.0 - 2.0 * d for d in range(1, 11)}
    result = analyze_median_split(outcome, lever)
    assert result.status == "ok" and result.inference == "observational"
    assert result.n_a == 5 and result.n_b == 5
    assert result.direction == "decrease"  # outcome lower on high-lever days
    assert result.p_value is not None and result.p_value < 0.05
    assert "association" in result.caveat.lower()


def test_analyze_median_split_insufficient_history():
    lever = {date(2026, 1, d): float(d) for d in range(1, 4)}  # 3 days < 6
    outcome = {date(2026, 1, d): float(d) for d in range(1, 4)}
    result = analyze_median_split(outcome, lever)
    assert result.status == "insufficient" and result.inference == "insufficient"


# ── adherence ─────────────────────────────────────────────────────────────


def test_adherence_strong_when_lever_separates():
    cal = build_phase_calendar(START, block_days=2, design="ABAB")
    lever: dict[date, float] = {}
    for phase in cal:
        day = phase.start
        base = 10.0 if phase.label == "A" else 30.0
        while day < phase.end:
            lever[day] = base + (day.day % 2)  # tiny spread, big A/B gap
            day = day.fromordinal(day.toordinal() + 1)
    check = adherence_from_lever(lever, cal)
    assert check.status == "strong"
    assert check.lever_effect_size is not None and check.lever_effect_size > 0.8


def test_adherence_none_when_lever_flat():
    cal = build_phase_calendar(START, block_days=2, design="ABAB")
    lever: dict[date, float] = {}
    for phase in cal:
        day = phase.start
        while day < phase.end:
            lever[day] = 20.0 + (day.day % 2) * 0.1  # essentially flat across A/B
            day = day.fromordinal(day.toordinal() + 1)
    check = adherence_from_lever(lever, cal)
    assert check.status == "none"


# ── summary ───────────────────────────────────────────────────────────────


def test_summarize_wording():
    values, cal = _abab_series(50.0, 60.0, block_days=2, design="ABAB")
    values[START] = 49.0
    pc = analyze_abab(values, cal)
    text = summarize(pc, outcome_short="resting heart rate", period_phrase="intervention blocks")
    assert "resting heart rate" in text.lower()
    assert "higher" in text and "intervention blocks" in text
    assert "d=" in text
