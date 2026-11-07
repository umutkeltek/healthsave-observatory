"""MCP read server: the summaries it hands an AI client (packages/mcp, no network).

These fail if a summary is shallow in the ways that would mislead a person:
awake time counted as sleep, two devices' steps added together, a daily total
landing on the wrong day, or a cut window passed off as complete.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from healthsave_mcp import derive
from healthsave_mcp.derive import TimeBasis, time_basis

ISTANBUL = time_basis({"time_zone": "Europe/Istanbul", "day_boundary_minutes": 240})


def _stage(start: datetime, minutes: float, code: str, stream: str = "watch") -> dict:
    return {
        "t": start.isoformat(),
        "interval_end": (start + timedelta(minutes=minutes)).isoformat(),
        "value": None,
        "code": code,
        "stream_id": stream,
        "source_id": "apple_health",
    }


def _night(evening: date, *, stream: str = "watch", awake_min: int = 20) -> list[dict]:
    """22:00 UTC bedtime: 2 h core, awake, 2 h deep, 2 h rem."""

    t = datetime(evening.year, evening.month, evening.day, 22, tzinfo=UTC)
    points = []
    for code, minutes in (("Core", 120), ("Awake", awake_min), ("Deep", 120), ("REM", 120)):
        points.append(_stage(t, minutes, code, stream))
        t += timedelta(minutes=minutes)
    return points


# ─── time basis ────────────────────────────────────────────────────────


def test_time_basis_reads_the_persons_setting_and_falls_back_to_utc() -> None:
    assert ISTANBUL.source == "settings" and ISTANBUL.day_start_minutes == 240
    assert ISTANBUL.describe() == "Europe/Istanbul, days start 04:00"
    for bad in (None, {}, {"time_zone": "Not/AZone"}, {"time_zone": 3}):
        assert time_basis(bad) is derive.UTC_BASIS


def test_a_reading_before_the_day_start_belongs_to_the_day_before() -> None:
    # 03:30 local in Istanbul (00:30 UTC) is still the previous analytical day.
    assert derive.analytical_day(datetime(2026, 3, 10, 0, 30, tzinfo=UTC), ISTANBUL) == date(
        2026, 3, 9
    )
    assert derive.analytical_day(datetime(2026, 3, 10, 2, 0, tzinfo=UTC), ISTANBUL) == date(
        2026, 3, 10
    )


@pytest.mark.parametrize("offset_hours", [3, -8, 0, 11])
def test_a_daily_total_at_local_midnight_stays_on_its_own_day(offset_hours) -> None:
    # The phone stamps the total at its local midnight; read in UTC the
    # instant falls on the previous date for every positive offset.
    local_midnight = datetime(2026, 5, 2, tzinfo=UTC) - timedelta(hours=offset_hours)
    point = {"t": local_midnight.isoformat()}
    assert derive.total_day(point, local_midnight, derive.UTC_BASIS) == date(2026, 5, 2)
    with_offset = {**point, "tz_offset_minutes": offset_hours * 60}
    assert derive.total_day(with_offset, local_midnight, derive.UTC_BASIS) == date(2026, 5, 2)


# ─── sleep ─────────────────────────────────────────────────────────────


def test_awake_inside_the_night_is_not_counted_as_sleep() -> None:
    [night] = derive.sleep_nights(_night(date(2026, 3, 1), awake_min=30), derive.UTC_BASIS)
    assert night.asleep_min == 360
    assert night.in_bed_min == 390
    assert night.stage_min["awake"] == 30
    shown = night.as_dict(derive.UTC_BASIS)
    assert shown["asleep_h"] == 6.0 and shown["efficiency_pct"] == 92
    assert shown["night_of"] == "2026-03-01"
    assert (shown["bedtime"], shown["wake"]) == ("22:00", "04:30")


def test_a_night_that_starts_after_midnight_counts_for_the_evening_before() -> None:
    t = datetime(2026, 3, 2, 1, 15, tzinfo=UTC)
    [night] = derive.sleep_nights([_stage(t, 300, "Core")], derive.UTC_BASIS)
    assert night.night_of == date(2026, 3, 1)


def test_two_sources_overlapping_are_one_night_not_two_and_not_double_time() -> None:
    watch = _night(date(2026, 3, 1), stream="watch")
    ring = _night(date(2026, 3, 1), stream="ring")
    [night] = derive.sleep_nights(watch + ring, derive.UTC_BASIS)
    assert night.asleep_min == 360  # the union, not 720
    assert night.sources == 2


def test_sources_that_disagree_show_conflict_and_awake_wins_for_sleep_time() -> None:
    t = datetime(2026, 3, 1, 22, tzinfo=UTC)
    points = [
        _stage(t, 120, "Deep", "watch"),
        _stage(t, 120, "REM", "ring"),  # two detailed stages: conflict, still asleep
        _stage(t + timedelta(minutes=120), 60, "Core", "watch"),
        _stage(t + timedelta(minutes=120), 60, "Awake", "ring"),  # awake: not asleep
    ]
    [night] = derive.sleep_nights(points, derive.UTC_BASIS)
    assert night.stage_min["conflict"] == 180
    assert night.asleep_min == 120


def test_a_four_hour_gap_splits_sessions_and_a_short_nap_is_not_a_night() -> None:
    first = _night(date(2026, 3, 1))
    nap = [_stage(datetime(2026, 3, 2, 14, tzinfo=UTC), 40, "Core")]
    second = _night(date(2026, 3, 2))
    nights = derive.sleep_nights(first + nap + second, derive.UTC_BASIS)
    assert [n.night_of for n in nights] == [date(2026, 3, 1), date(2026, 3, 2)]


def test_malformed_and_absurd_segments_are_dropped() -> None:
    t = datetime(2026, 3, 1, 22, tzinfo=UTC)
    bad = [
        {"t": t.isoformat(), "interval_end": t.isoformat(), "code": "Core"},  # zero length
        {"t": t.isoformat(), "interval_end": (t + timedelta(days=2)).isoformat(), "code": "Core"},
        {"t": "not a time", "interval_end": t.isoformat(), "code": "Core"},
        {"t": t.isoformat(), "interval_end": (t + timedelta(hours=2)).isoformat(), "code": None},
    ]
    assert derive.sleep_nights(bad, derive.UTC_BASIS) == []


def test_sleep_summary_and_months_describe_every_night() -> None:
    nights = derive.sleep_nights(
        [p for d in range(40) for p in _night(date(2026, 1, 1) + timedelta(days=d))],
        derive.UTC_BASIS,
    )
    summary = derive.sleep_summary(nights, derive.UTC_BASIS)
    assert summary["nights"] == 40
    assert summary["asleep_h"]["median"] == 6.0
    assert summary["typical_bedtime"] == "22:00" and summary["typical_wake"] == "04:20"
    assert summary["stage_share_pct"] == {"core": 33, "deep": 33, "rem": 33}
    months = derive.sleep_months(nights, derive.UTC_BASIS)
    assert [(m["month"], m["nights"]) for m in months] == [("2026-01", 31), ("2026-02", 9)]


def test_bedtimes_either_side_of_midnight_have_a_sensible_typical_time() -> None:
    nights = []
    for d, hour in enumerate([23, 0, 23, 0, 23]):
        day = date(2026, 3, 1) + timedelta(days=d)
        start = datetime(day.year, day.month, day.day, hour, 30, tzinfo=UTC) + timedelta(
            days=1 if hour == 0 else 0
        )
        nights += derive.sleep_nights([_stage(start, 420, "Core")], derive.UTC_BASIS)
    summary = derive.sleep_summary(nights, derive.UTC_BASIS)
    assert summary["typical_bedtime"] == "23:30"  # not noon, not 12:00


# ─── daily values ──────────────────────────────────────────────────────


def _total(day: date, value: float, scope: str, stream: str) -> dict:
    t = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return {
        "t": t.isoformat(),
        "interval_end": (t + timedelta(days=1)).isoformat(),
        "value": value,
        "aggregation_scope": scope,
        "stream_id": stream,
    }


def test_daily_totals_read_the_all_source_total_and_never_add_devices() -> None:
    day = date(2026, 4, 1)
    points = [
        _total(day, 9000, "owner_all_source_day_total", "phone-all"),
        _total(day, 7000, "device_day_total", "watch"),
        _total(day, 6500, "device_day_total", "ring"),
    ]
    daily = derive.daily_totals(points, derive.UTC_BASIS)
    assert daily.values == {day: 9000}
    assert daily.basis == "all_source_day_total"


def test_without_an_all_source_total_one_device_is_used_and_the_other_left_out() -> None:
    days = [date(2026, 4, 1) + timedelta(days=i) for i in range(3)]
    points = [_total(d, 7000, "device_day_total", "watch") for d in days]
    points += [_total(days[0], 6500, "device_day_total", "ring")]
    daily = derive.daily_totals(points, derive.UTC_BASIS)
    assert daily.values == {d: 7000 for d in days}  # never 13,500
    assert daily.basis == "one_stream_total" and daily.other_streams == 1


def test_interval_components_of_one_stream_are_summed_per_day() -> None:
    t = datetime(2026, 4, 1, 9, tzinfo=UTC)
    points = [
        {"t": (t + timedelta(hours=h)).isoformat(), "value": 500, "stream_id": "watch"}
        for h in range(4)
    ]
    assert derive.daily_totals(points, derive.UTC_BASIS).values == {date(2026, 4, 1): 2000}


def test_daily_readings_take_median_low_high_and_skip_day_totals() -> None:
    t = datetime(2026, 4, 1, 9, tzinfo=UTC)
    points = [
        {"t": (t + timedelta(hours=h)).isoformat(), "value": v, "stream_id": "watch"}
        for h, v in enumerate([60, 70, 100])
    ]
    points.append(_total(date(2026, 4, 1), 12345, "device_day_total", "watch"))
    daily = derive.daily_readings(points, derive.UTC_BASIS)
    day = date(2026, 4, 1)
    assert (daily.values[day], daily.lows[day], daily.highs[day], daily.counts[day]) == (
        70,
        60,
        100,
        3,
    )


def test_a_response_at_the_server_cap_is_reported_as_cut() -> None:
    t = datetime(2026, 1, 1, tzinfo=UTC)
    full = [{"t": (t + timedelta(minutes=i)).isoformat()} for i in range(derive.SERVER_POINT_CAP)]
    assert derive.truncated(full) == t
    assert derive.truncated(full[:-1]) is None


# ─── small statistics ──────────────────────────────────────────────────


def test_quantiles_match_numpy_linear_and_ignore_non_finite() -> None:
    assert derive.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert derive.quantile([1, 2, 3, 4, 5], 0.1) == pytest.approx(1.4)
    assert derive.quantile([float("nan"), 3], 0.5) == 3
    assert derive.quantile([], 0.5) is None


def test_usual_range_and_place_never_judge_only_compare() -> None:
    band = derive.usual_range([50, 52, 54, 56, 58, 60, 62])
    assert band == {"median": 56, "low": 51.2, "high": 60.8, "days": 7}
    assert [derive.place(v, band) for v in (49, 56, 70)] == ["below", "within", "above"]
    assert derive.place(None, band) is None and derive.place(1, None) is None


def test_runs_of_missing_lists_every_run_including_single_days() -> None:
    days = derive.date_range(date(2026, 8, 1), date(2026, 8, 12))
    present = {d for d in days if not (date(2026, 8, 3) <= d <= date(2026, 8, 5))}
    present.discard(date(2026, 8, 10))
    assert derive.runs_of_missing(days, present) == [
        {"from": "2026-08-03", "to": "2026-08-05", "days": 3},
        {"from": "2026-08-10", "to": "2026-08-10", "days": 1},
    ]


def test_utc_basis_is_a_time_basis() -> None:
    assert isinstance(derive.UTC_BASIS, TimeBasis)


def test_a_streams_day_total_replaces_its_components_never_adds_to_them() -> None:
    day = date(2026, 4, 1)
    t = datetime(2026, 4, 1, 9, tzinfo=UTC)
    points = [_total(day, 7000, "device_day_total", "watch")] + [
        {"t": (t + timedelta(hours=h)).isoformat(), "value": 1000, "stream_id": "watch"}
        for h in range(3)
    ]
    assert derive.daily_totals(points, derive.UTC_BASIS).values == {day: 7000}  # not 10,000


def test_days_without_the_all_source_total_are_counted_not_mixed_in() -> None:
    covered, bare = date(2026, 4, 1), date(2026, 4, 2)
    points = [
        _total(covered, 9000, "owner_all_source_day_total", "phone-all"),
        {"t": datetime(2026, 4, 2, 9, tzinfo=UTC).isoformat(), "value": 400, "stream_id": "g"},
    ]
    daily = derive.daily_totals(points, derive.UTC_BASIS)
    assert daily.values == {covered: 9000} and daily.uncovered_days == 1
    assert bare not in daily.values


def test_the_package_runs_on_python_310() -> None:
    # The server runs on the AI client's computer (requires-python >= 3.10);
    # datetime.UTC only exists from 3.11.
    import healthsave_mcp

    root = Path(healthsave_mcp.__file__).parent
    for source in root.glob("*.py"):
        text = source.read_text()
        assert "import UTC" not in text and "datetime.UTC" not in text, source.name
