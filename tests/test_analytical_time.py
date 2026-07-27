from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from contracts.analytical_time import (
    AnalyticalTime,
    analytical_day,
    analytical_day_bounds,
    sleep_day,
)


def test_boundary_keeps_after_midnight_reading_on_previous_physiological_day() -> None:
    config = AnalyticalTime("Europe/Istanbul", 4 * 60)
    assert analytical_day(datetime(2026, 7, 10, 0, 30, tzinfo=UTC), config) == date(2026, 7, 9)
    assert analytical_day(datetime(2026, 7, 10, 1, 30, tzinfo=UTC), config) == date(2026, 7, 10)


def test_same_instant_maps_differently_by_person_timezone() -> None:
    instant = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    assert analytical_day(instant, AnalyticalTime("Pacific/Honolulu", 0)) == date(2026, 7, 9)
    assert analytical_day(instant, AnalyticalTime("Asia/Tokyo", 0)) == date(2026, 7, 10)


def test_sleep_session_is_assigned_by_wake_time() -> None:
    config = AnalyticalTime("Europe/Istanbul", 4 * 60)
    wake = datetime(2026, 7, 10, 4, 30, tzinfo=UTC)  # 07:30 local
    assert sleep_day(wake, config) == date(2026, 7, 10)


def test_dst_bounds_are_23_or_25_real_hours_without_changing_local_boundary() -> None:
    config = AnalyticalTime("Europe/Berlin", 4 * 60)
    # With a 04:00 boundary, the DST transition belongs to the preceding
    # analytical date because the civil-clock jump occurs before 04:00.
    spring_start, spring_end = analytical_day_bounds(date(2026, 3, 28), config)
    fall_start, fall_end = analytical_day_bounds(date(2026, 10, 24), config)
    assert (spring_end - spring_start).total_seconds() == 23 * 3600
    assert (fall_end - fall_start).total_seconds() == 25 * 3600
    assert spring_start.astimezone(config.zone).hour == 4
    assert fall_start.astimezone(config.zone).hour == 4


def test_invalid_timezone_boundary_and_naive_timestamp_fail_loudly() -> None:
    with pytest.raises(ValueError, match="unknown IANA"):
        AnalyticalTime("Mars/Olympus")
    with pytest.raises(ValueError, match="day_boundary_minutes"):
        AnalyticalTime("UTC", 12 * 60 + 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        analytical_day(datetime(2026, 7, 10, 8), AnalyticalTime())


def test_boundary_label_is_stable_for_ui_and_evidence_metadata() -> None:
    assert AnalyticalTime("UTC", 270).boundary_label == "04:30"
