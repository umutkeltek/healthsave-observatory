"""Year in Health engine (pure): months, gaps, device changes, headlines.

The two promises this file guards hardest:
* no day without data is ever dropped from the gap list (per family and
  overall), whatever the pattern;
* a headline number belongs to one source; two sources are never averaged.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest
from analysis.statistical import year as engine
from contracts.analytical_time import AnalyticalTime

UTC_04 = AnalyticalTime("UTC", 240)
WATCH = "7c1f0c52-4c1b-5d0e-9a43-2a7f7d1b9e01"
RING = "0b9d7e1e-34a4-5f39-8d3c-6f1f6a2f0a02"
SCALE = "5a3c1c6b-1b51-5b74-9a8f-1e7b6fb40c03"
PHONE_TOTAL = "9e2d4f1a-77c0-5ad1-8f60-6c4f0b8b5d04"
WINDOW_2025 = (date(2025, 1, 1), date(2025, 12, 31))


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _presence(
    days, metric="vital.resting_heart_rate", category="vital", stream=WATCH, scope=None
) -> list[engine.DayPresence]:
    return [
        engine.DayPresence(
            metric_id=metric,
            category=category,
            stream_id=stream,
            scope=scope or "interval_component",
            day=day,
        )
        for day in days
    ]


def _at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def _streams(**bounds) -> dict[str, engine.StreamInfo]:
    names = {WATCH: "Apple Watch", RING: "Oura Ring", SCALE: "Withings Body+"}
    return {
        stream: engine.StreamInfo(stream, names.get(stream, stream), "apple_health", first, last)
        for stream, (first, last) in bounds.items()
    }


def _summary(presence, streams=None, window=WINDOW_2025, headline_metrics=()):
    return engine.summarize_year(
        year=window[0].year,
        window=window,
        presence=presence,
        streams=streams or {},
        config=UTC_04,
        headline_metrics=headline_metrics,
    )


# ── window ───────────────────────────────────────────────────────────────


def test_year_window_past_current_and_future():
    assert engine.year_window(2025, date(2026, 11, 7)) == WINDOW_2025
    assert engine.year_window(2026, date(2026, 11, 7)) == (date(2026, 1, 1), date(2026, 11, 7))
    assert engine.year_window(2027, date(2026, 11, 7)) is None


# ── gaps: nothing is hidden ──────────────────────────────────────────────


def _assert_runs_partition(mask: str, start: date, runs) -> None:
    zeros = {start + timedelta(days=i) for i, ch in enumerate(mask) if ch == "0"}
    covered: list[date] = []
    for run in runs:
        assert run.days == (run.end - run.start).days + 1
        covered.extend(_days(run.start, run.end))
    assert len(covered) == len(set(covered)), "gap runs overlap"
    assert set(covered) == zeros, "a day without data is missing from the gap list"


@pytest.mark.parametrize("seed", range(40))
def test_gap_runs_partition_every_day_without_data(seed):
    rng = random.Random(seed)
    length = rng.randint(1, 366)
    density = rng.choice([0.0, 0.05, 0.3, 0.7, 0.97, 1.0])
    mask = "".join("1" if rng.random() < density else "0" for _ in range(length))
    runs = engine.gap_runs(mask, date(2025, 1, 1))
    _assert_runs_partition(mask, date(2025, 1, 1), runs)
    if "1" in mask:
        first, last = mask.index("1"), mask.rindex("1")
        for run in runs:
            i = (run.start - date(2025, 1, 1)).days
            j = (run.end - date(2025, 1, 1)).days
            expected = "before_first" if j < first else "after_last" if i > last else "inside"
            assert run.kind == expected
    elif mask:
        assert [run.kind for run in runs] == ["no_data"]


def test_single_day_gaps_are_kept():
    mask = "1101011"
    runs = engine.gap_runs(mask, date(2025, 3, 1))
    assert [(r.start.day, r.days, r.kind) for r in runs] == [(3, 1, "inside"), (5, 1, "inside")]


@pytest.mark.parametrize("seed", range(10))
def test_summary_never_hides_a_gap(seed):
    rng = random.Random(1000 + seed)
    presence = []
    families = [
        ("vital.resting_heart_rate", "vital", WATCH),
        ("sleep.stage", "sleep", RING),
        ("body.weight", "body", SCALE),
        ("activity.steps", "activity", PHONE_TOTAL),
    ]
    for metric, category, stream in families:
        density = rng.choice([0.1, 0.5, 0.95])
        days = [d for d in _days(*WINDOW_2025) if rng.random() < density]
        presence += _presence(days, metric=metric, category=category, stream=stream)
    summary = _summary(presence)

    _assert_runs_partition(summary.mask, summary.window_start, summary.gaps)
    for family in summary.families:
        assert len(family.mask) == summary.days_in_window
        _assert_runs_partition(family.mask, summary.window_start, family.gaps)
        assert sum(run.days for run in family.gaps) == family.days_without_data
        assert family.days_with_data + family.days_without_data == summary.days_in_window
    assert sum(run.days for run in summary.gaps) == summary.days_in_window - summary.days_with_data
    # The per-day family count agrees with the masks, day by day.
    for i, count in enumerate(summary.day_family_counts):
        assert count == sum(1 for f in summary.families if f.mask[i] == "1")


def test_a_nine_day_august_gap_is_reported_with_its_dates():
    days = [d for d in _days(*WINDOW_2025) if not date(2025, 8, 3) <= d <= date(2025, 8, 11)]
    summary = _summary(_presence(days))
    heart = summary.families[0]
    assert heart.id == "heart"
    assert [(g.start, g.end, g.days, g.kind) for g in heart.gaps] == [
        (date(2025, 8, 3), date(2025, 8, 11), 9, "inside")
    ]
    assert heart.longest_inside_gap == 9
    assert summary.longest_inside_gap == 9
    august = summary.months[7]
    assert (august.days, august.days_with_data, august.confidence) == (31, 22, "ok")


def test_a_late_start_is_before_first_not_inside():
    days = _days(date(2025, 6, 1), date(2025, 12, 31))
    summary = _summary(_presence(days))
    assert [(g.kind, g.days) for g in summary.gaps] == [("before_first", 151)]
    assert summary.longest_inside_gap == 0
    codes = {item.code: item for item in summary.limitations}
    assert codes["record_starts_late"].day == date(2025, 6, 1)
    assert summary.months[0].confidence == "none"
    assert summary.months[5].confidence == "ok"


# ── months and confidence ────────────────────────────────────────────────


def test_current_year_stops_today_and_marks_future_months():
    window = (date(2026, 1, 1), date(2026, 11, 7))
    days = [d for d in _days(*window) if d.day % 3 == 0]  # a third of the days
    summary = _summary(_presence(days), window=window)
    assert summary.days_in_window == 311
    november = summary.months[10]
    assert november.days == 7
    assert november.confidence == "low"
    assert summary.months[11].days == 0
    assert summary.months[11].coverage is None
    assert summary.months[11].confidence == "future"
    assert summary.confidence == "low"
    codes = {item.code: item for item in summary.limitations}
    assert codes["partial_year"].day == date(2026, 11, 7)


def test_empty_year_says_no_data():
    summary = _summary([])
    assert summary.days_with_data == 0
    assert summary.families == ()
    assert summary.confidence == "none"
    assert [(g.kind, g.days) for g in summary.gaps] == [("no_data", 365)]
    assert "no_data" in {item.code for item in summary.limitations}


def test_derived_metrics_are_not_counted_as_recorded_days():
    presence = _presence(
        [date(2025, 2, 1)], metric="sleep.regularity_index", category="computed", stream=None
    )
    summary = _summary(presence)
    assert summary.days_with_data == 0
    assert "derived_excluded" in {item.code for item in summary.limitations}


# ── sources and device changes ───────────────────────────────────────────


def test_device_changes_come_from_observation_bounds():
    presence = _presence(_days(date(2025, 1, 1), date(2025, 6, 30)), stream=WATCH) + _presence(
        _days(date(2025, 4, 10), date(2025, 12, 31)),
        metric="sleep.stage",
        category="sleep",
        stream=RING,
    )
    streams = _streams(
        **{
            # The watch started long before 2025 and stopped in June.
            WATCH: (_at(date(2023, 5, 2)), _at(date(2025, 6, 30))),
            # The ring is new this year and still going.
            RING: (_at(date(2025, 4, 10)), _at(date(2025, 12, 31))),
        }
    )
    summary = _summary(presence, streams)
    by_id = {s.stream_id: s for s in summary.sources}
    assert by_id[WATCH].new_this_year is False
    assert by_id[WATCH].stopped_this_year is True
    assert by_id[RING].new_this_year is True
    assert by_id[RING].stopped_this_year is False
    assert by_id[RING].months == tuple(range(4, 13))
    assert [(c.day, c.kind, c.label) for c in summary.device_changes] == [
        (date(2025, 4, 10), "first_seen", "Oura Ring"),
        (date(2025, 6, 30), "last_seen", "Apple Watch"),
    ]
    assert summary.months[3].first_seen_ids == (RING,)
    assert summary.months[5].last_seen_ids == (WATCH,)
    assert set(summary.months[4].source_ids) == {WATCH, RING}
    assert "device_labels" in {item.code for item in summary.limitations}


def test_a_short_silence_at_the_end_is_not_a_stopped_device():
    window = (date(2026, 1, 1), date(2026, 11, 7))
    presence = _presence(_days(date(2026, 1, 1), date(2026, 11, 1)))
    streams = _streams(**{WATCH: (_at(date(2024, 1, 1)), _at(date(2026, 11, 1)))})
    summary = _summary(presence, streams, window=window)
    assert summary.sources[0].stopped_this_year is False
    assert summary.device_changes == ()


def test_all_source_day_totals_count_as_data_but_never_as_a_source():
    presence = _presence(
        _days(date(2025, 1, 1), date(2025, 1, 31)),
        metric="activity.steps",
        category="activity",
        stream=PHONE_TOTAL,
        scope="owner_all_source_day_total",
    )
    summary = _summary(presence, _streams(**{PHONE_TOTAL: (None, None)}))
    assert summary.days_with_data == 31
    assert [f.id for f in summary.families] == ["activity"]
    assert summary.sources == ()


def test_rows_without_a_stream_are_disclosed():
    presence = _presence([date(2025, 5, 5)], stream=None)
    summary = _summary(presence)
    codes = {item.code: item for item in summary.limitations}
    assert codes["unattributed"].count == 1


# ── headlines: one source at a time ──────────────────────────────────────


def _daily(value: float, days: int, start=date(2025, 1, 1)):
    return [(_at(start + timedelta(days=i), 6), value + (i % 3 - 1)) for i in range(days)]


def test_headlines_are_per_source_and_never_averaged():
    metric = engine.HeadlineMetric(
        id="resting_heart_rate",
        metric_id="vital.resting_heart_rate",
        label="Resting heart rate",
        unit="bpm",
        samples_by_stream={WATCH: _daily(56, 200), RING: _daily(50, 200)},
    )
    streams = _streams(**{WATCH: (None, None), RING: (None, None)})
    summary = _summary([], streams, headline_metrics=[metric])
    rhr = [h for h in summary.headlines if h.id == "resting_heart_rate"]
    assert {(h.source_label, h.value) for h in rhr} == {("Apple Watch", 56.0), ("Oura Ring", 50.0)}
    assert all(h.basis == "median_one_source" for h in rhr)
    # The pooled answer (53) must not appear anywhere.
    assert 53.0 not in {h.value for h in summary.headlines}


def test_headline_needs_seven_days_and_is_low_confidence_under_thirty():
    metric = engine.HeadlineMetric(
        id="resting_heart_rate",
        metric_id="vital.resting_heart_rate",
        label="Resting heart rate",
        unit="bpm",
        samples_by_stream={WATCH: _daily(56, 20), RING: _daily(50, 5)},
    )
    streams = _streams(**{WATCH: (None, None), RING: (None, None)})
    summary = _summary([], streams, headline_metrics=[metric])
    shown = [h for h in summary.headlines if h.id == "resting_heart_rate"]
    assert [(h.source_label, h.confidence, h.days) for h in shown] == [("Apple Watch", "low", 20)]
    assert [(w.source_label, w.days, w.reason) for w in summary.withheld] == [
        ("Oura Ring", 5, "too_few_days")
    ]
    assert "headline_thin" in {item.code for item in summary.limitations}


def test_all_source_day_total_is_its_own_labelled_series():
    metric = engine.HeadlineMetric(
        id="steps",
        metric_id="activity.steps",
        label="Daily steps",
        unit="steps",
        samples_by_stream={None: _daily(8000, 120)},
        all_sources_label="All sources, daily total",
    )
    summary = _summary([], headline_metrics=[metric])
    steps = [h for h in summary.headlines if h.id == "steps"]
    assert [(h.stream_id, h.source_label, h.value, h.basis) for h in steps] == [
        (None, "All sources, daily total", 8000.0, "median_all_sources_total")
    ]


def test_record_headlines_count_days_sources_and_longest_gap():
    days = [d for d in _days(*WINDOW_2025) if d.month != 2]
    presence = _presence(days)
    streams = _streams(**{WATCH: (_at(date(2024, 1, 1)), _at(date(2026, 1, 1)))})
    summary = _summary(presence, streams)
    by_id = {h.id: h for h in summary.headlines}
    assert (by_id["days_recorded"].value, by_id["days_recorded"].of_days) == (337, 365)
    assert by_id["sources"].value == 1
    assert by_id["longest_gap"].value == 28
