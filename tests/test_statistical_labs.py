"""Lab reader engine (pure): bands, assessment, gaps, and the cross-match card."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from analysis.statistical.labs import (
    MIN_WINDOW_DAYS,
    PAIRINGS,
    LabPoint,
    WearableSample,
    assess_marker,
    band_position,
    cross_match_card,
    lab_gaps,
)
from contracts.findings import FindingCard

NORTH, HARBOR = "stream-north", "stream-harbor"
WATCH, RING = "stream-watch", "stream-ring"
RHR = PAIRINGS["2276-4"]


def _p(day: str, value: float, *, lab=NORTH, low=30.0, high=400.0, comparator=None, unit="ng/mL"):
    return LabPoint(
        specimen_at=datetime.fromisoformat(day).replace(tzinfo=UTC),
        value=value,
        unit=unit,
        stream_id=lab,
        lab="Northfield Diagnostics" if lab == NORTH else "Harbor Clinical Lab",
        comparator=comparator,
        reference_low=low,
        reference_high=high,
    )


def _daily(end: str, days: int, value_for_day) -> list[WearableSample]:
    stop = datetime.fromisoformat(end).replace(tzinfo=UTC)
    return [
        WearableSample(stop - timedelta(days=offset, hours=-6), value_for_day(offset))
        for offset in range(1, days + 1)
    ]


# ── Bands ─────────────────────────────────────────────────────────


def test_band_positions_use_the_lab_s_own_range() -> None:
    assert band_position(_p("2026-01-01", 24)).status == "below"
    assert band_position(_p("2026-01-01", 24)).distance == pytest.approx(6)
    within = band_position(_p("2026-01-01", 215))
    assert (within.status, within.fraction) == ("within", pytest.approx(0.5))
    assert band_position(_p("2026-01-01", 500)).status == "above"
    assert band_position(_p("2026-01-01", 24, low=None, high=None)).status == "no_range"
    assert band_position(_p("2026-01-01", 24, low=15, high=None)).status == "within"


def test_censored_values_only_judged_when_the_limit_decides() -> None:
    assert band_position(_p("2026-01-01", 0.5, low=None, high=5, comparator="<")).status == (
        "within"
    )
    assert band_position(_p("2026-01-01", 10, low=30, high=400, comparator="<")).status == "below"
    assert band_position(_p("2026-01-01", 50, low=30, high=400, comparator="<")).status == (
        "censored"
    )


# ── Assessment ────────────────────────────────────────────────────


def test_assessment_compares_latest_with_previous_and_history() -> None:
    result = assess_marker([_p("2025-11-18", 64), _p("2026-03-10", 41), _p("2026-09-08", 24)])
    assert result is not None
    assert result.latest.value == 24
    assert result.latest_band.status == "below"
    assert result.change == pytest.approx(-17)
    assert result.change_pct == pytest.approx(-41.463, abs=1e-3)
    assert result.direction == "down"
    assert result.prior_count == 2
    assert (result.prior_min, result.prior_max) == (41, 64)
    assert result.versus_history == "below_prior_range"
    assert result.outside_streak == 1
    assert result.previous_from_other_lab is False


def test_assessment_flags_a_previous_result_from_another_lab() -> None:
    result = assess_marker([_p("2026-09-08", 24), _p("2026-09-17", 19, lab=HARBOR, low=15)])
    assert result is not None
    assert result.previous_from_other_lab is True
    assert result.latest_band.status == "within"  # Harbor's own range, not Northfield's


def test_assessment_withholds_change_for_censored_or_mixed_units() -> None:
    censored = assess_marker([_p("2026-01-01", 3), _p("2026-02-01", 0.5, comparator="<")])
    assert censored is not None and censored.change is None and censored.direction is None
    assert "limit" in (censored.change_withheld or "")
    mixed = assess_marker([_p("2026-01-01", 3), _p("2026-02-01", 30, unit="ng/cc")])
    assert mixed is not None and mixed.change is None
    first = assess_marker([_p("2026-01-01", 3)])
    assert first is not None and first.change_withheld == "first result"


def test_outside_streak_counts_consecutive_recent_results() -> None:
    result = assess_marker(
        [_p("2026-01-01", 50), _p("2026-02-01", 25), _p("2026-03-01", 20), _p("2026-04-01", 10)]
    )
    assert result is not None and result.outside_streak == 3


def test_empty_series_has_no_assessment() -> None:
    assert assess_marker([]) is None


# ── Gaps between labs ─────────────────────────────────────────────


def test_gap_shows_both_labs_and_never_a_mean() -> None:
    gaps = lab_gaps([_p("2026-09-08", 24), _p("2026-09-17", 19, lab=HARBOR, low=15, high=300)])
    (gap,) = gaps
    assert (gap.earlier.value, gap.later.value) == (24, 19)
    assert gap.difference == pytest.approx(-5)
    assert gap.difference_pct == pytest.approx(-20.833, abs=1e-3)
    assert gap.days_apart == pytest.approx(9.0)
    assert (gap.earlier_band.status, gap.later_band.status) == ("below", "within")
    assert gap.bands_disagree is True
    assert not hasattr(gap, "mean")


def test_no_gap_for_one_lab_or_far_apart_results() -> None:
    assert lab_gaps([_p("2026-09-08", 24), _p("2026-09-10", 26)]) == []
    assert lab_gaps([_p("2026-06-01", 24), _p("2026-09-17", 19, lab=HARBOR)]) == []


# ── Cross-match card ──────────────────────────────────────────────


def _three_draws():
    return [_p("2025-11-18", 64), _p("2026-03-10", 41), _p("2026-09-08", 24)]


def _rhr_for_draws(draws, values):
    samples = []
    for draw, base in zip(draws, values, strict=True):
        end = draw.specimen_at.date().isoformat()
        samples += _daily(end, 30, lambda offset, base=base: base + (offset % 3) * 0.5)
    return samples


def test_cross_match_card_compares_the_two_latest_windows_on_one_stream() -> None:
    draws = _three_draws()
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={WATCH: _rhr_for_draws(draws, [57, 58, 62])},
        stream_labels={WATCH: "Apple Watch"},
        stream_plugins={WATCH: "apple-healthkit-ios"},
    )
    card = match.card
    assert isinstance(card, FindingCard)
    assert card.finding_type == "lab_wearable_cross_match"
    assert card.metric == "loinc:2276-4"
    assert "Ferritin went from 41 to 24 ng/mL (2026-03-10 to 2026-09-08)" in card.claim
    assert "58.5 then 62.5 bpm (Apple Watch)" in card.claim
    assert card.delta is not None and card.delta.direction == "up"
    assert card.delta.absolute == pytest.approx(4.0)
    assert card.effect_size is not None and card.effect_size.kind == "cohens_d"
    assert card.confidence == "low"  # three draws
    assert card.coverage is not None and card.coverage.days_with_data == 30
    assert card.current_window is not None and card.current_window.n == 30
    assert [s.source_plugin_id for s in card.sources] == ["labs-csv", "apple-healthkit-ios"]
    assert any("not cause and effect" in item for item in card.limitations)


def test_cross_match_uses_spearman_from_four_draws_and_caps_confidence() -> None:
    draws = [
        _p(day, value)
        for day, value in (
            ("2025-03-01", 80),
            ("2025-06-01", 64),
            ("2025-09-01", 52),
            ("2025-12-01", 41),
            ("2026-03-01", 30),
            ("2026-06-01", 24),
        )
    ]
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={WATCH: _rhr_for_draws(draws, [55, 56, 57, 58, 60, 62])},
    )
    card = match.card
    assert card is not None and card.effect_size is not None
    assert card.effect_size.kind == "spearman_rho"
    assert card.effect_size.value == pytest.approx(-1.0)
    assert card.effect_size.p_value is not None and card.effect_size.p_value < 0.01
    assert card.confidence == "medium"  # p < 0.01 but fewer than 8 draws


def test_other_streams_are_named_not_averaged() -> None:
    draws = _three_draws()
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={
            WATCH: _rhr_for_draws(draws, [57, 58, 62]),
            RING: _daily("2026-09-08", 10, lambda offset: 50.0),  # fewer days: not chosen
        },
        stream_labels={WATCH: "Apple Watch", RING: "Oura Ring"},
    )
    assert match.stream_id == WATCH
    card = match.card
    assert card is not None
    assert "62.5 bpm" in card.claim  # ring's 50 bpm never pulled the mean
    assert any("Oura Ring also recorded" in item for item in card.limitations)


def test_no_card_without_coverage_and_the_reason_says_why() -> None:
    draws = _three_draws()
    thin = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={WATCH: _daily("2026-09-08", MIN_WINDOW_DAYS - 1, lambda o: 60.0)},
        stream_labels={WATCH: "Apple Watch"},
    )
    assert thin.card is None
    assert thin.reason == (
        "Only 20 of 30 days of resting heart rate (Apple Watch) before the 2026-09-08 draw; "
        "21 are needed."
    )
    none = cross_match_card(
        loinc="2276-4", marker_name="Ferritin", points=draws, pairing=RHR, wearable={}
    )
    assert none.card is None and "No resting heart rate data" in (none.reason or "")


def test_one_covered_draw_gives_a_descriptive_card_without_effect_size() -> None:
    draws = _three_draws()
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={WATCH: _daily("2026-09-08", 30, lambda o: 60.0)},
    )
    card = match.card
    assert card is not None
    assert card.delta is None and card.effect_size is None and card.baseline_window is None
    assert card.claim.startswith("Ferritin was 24 ng/mL on 2026-09-08.")


def test_censored_latest_result_is_not_compared() -> None:
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=[_p("2026-09-08", 5, comparator="<")],
        pairing=RHR,
        wearable={WATCH: _daily("2026-09-08", 30, lambda o: 60.0)},
    )
    assert match.card is None and "limit" in (match.reason or "")


def test_pairings_never_use_rmssd() -> None:
    assert all("rmssd" not in pairing.metric_id for pairing in PAIRINGS.values())


def test_engine_imports_no_db_http_or_llm() -> None:
    source = Path(__file__).resolve().parents[1] / "packages/py/analysis/statistical/labs.py"
    tree = ast.parse(source.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "math",
        "statistics",
        "collections",
        "dataclasses",
        "datetime",
        "typing",
        "contracts",
        "warnings",
        "scipy",
        "itertools",
    }


def test_four_draws_in_perfect_order_are_not_significant() -> None:
    # Exact two-sided p for a perfect rank order of 4 draws is 2/24, not 0.
    draws = [
        _p(day, value)
        for day, value in (
            ("2025-06-01", 80),
            ("2025-09-01", 60),
            ("2025-12-01", 45),
            ("2026-03-01", 30),
        )
    ]
    match = cross_match_card(
        loinc="2276-4",
        marker_name="Ferritin",
        points=draws,
        pairing=RHR,
        wearable={WATCH: _rhr_for_draws(draws, [55, 57, 59, 61])},
    )
    card = match.card
    assert card is not None and card.effect_size is not None
    assert card.effect_size.value == pytest.approx(-1.0)
    assert card.effect_size.p_value == pytest.approx(2 / 24, abs=1e-4)
    assert card.confidence == "low"


def test_draws_with_overlapping_windows_are_not_counted_twice() -> None:
    draws = [_p("2026-03-10", 41), _p("2026-09-08", 24), _p("2026-09-17", 19, lab=HARBOR, low=15)]
    samples = _daily("2026-09-17", 260, lambda offset: 60.0 + offset % 2)
    match = cross_match_card(
        loinc="2276-4", marker_name="Ferritin", points=draws, pairing=RHR, wearable={WATCH: samples}
    )
    card = match.card
    assert card is not None
    assert "from 41 to 19" in card.claim  # Sep 8 overlaps Sep 17 and is left out
    assert any("left out, so no wearable day is counted twice" in item for item in card.limitations)
