"""Tests for the Whoop -> IngestStorage sample-shape normalizers.

Synthetic Whoop-shaped records cover:

  * one recovery -> five quantity-sample emissions (HRV, SpO2, skin
    temp, RHR, recovery_score).
  * sleep aggregates routed to quantity_samples (sleep_duration_hours,
    sleep_efficiency_percentage, sleep_respiratory_rate); session-end
    timestamp; in_bed minus awake = sleep duration.
  * workouts mapped to the iOS-emitted shape, with kJ -> kcal
    conversion and sport_id -> name fallback for unknown ids.
  * cycle strain + average HR; cycle HR tagged so it does not collide
    with workout HR.
  * non-SCORED records are skipped silently.
  * empty input lists return empty per-metric lists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.whoop.normalize import (  # noqa: E402
    SOURCE_TAG,
    normalize_body_measurement,
    normalize_cycles,
    normalize_recovery,
    normalize_sleep,
    normalize_workouts,
)


def test_normalize_body_measurement_emits_current_samples():
    out = normalize_body_measurement(
        {"height_meter": 1.78, "weight_kilogram": 75.0, "max_heart_rate": 195}
    )
    assert out["height_meters"][0]["qty"] == 1.78
    assert out["weight_kg"][0]["qty"] == 75.0
    assert out["max_heart_rate"][0]["qty"] == 195.0
    for metric in ("height_meters", "weight_kg", "max_heart_rate"):
        assert out[metric][0]["source"] == SOURCE_TAG
        assert out[metric][0]["date"]
    assert normalize_body_measurement({}) == {
        "height_meters": [],
        "weight_kg": [],
        "max_heart_rate": [],
    }


def test_normalize_recovery_emits_metrics_per_scored_item():
    out = normalize_recovery(
        [
            {
                "cycle_id": 1,
                "created_at": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {
                    "recovery_score": 73,
                    "resting_heart_rate": 58,
                    "hrv_rmssd_milli": 64.3,
                    "spo2_percentage": 97.0,
                    "skin_temp_celsius": 35.2,
                    "user_calibrating": True,
                },
            }
        ]
    )
    assert out["heart_rate_variability"] == [
        {"date": "2026-05-22T08:00:00Z", "qty": 64.3, "source": SOURCE_TAG}
    ]
    assert out["blood_oxygen"][0]["qty"] == 97.0
    assert out["body_temperature"][0]["qty"] == 35.2
    assert out["resting_heart_rate"][0]["qty"] == 58.0
    assert out["recovery_score"][0]["qty"] == 73.0
    assert out["recovery_calibrating"][0]["qty"] == 1.0
    for samples in out.values():
        assert all(s["source"] == SOURCE_TAG for s in samples)


def test_normalize_recovery_skips_missing_fields_silently():
    out = normalize_recovery(
        [
            {
                "cycle_id": 1,
                "created_at": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {"recovery_score": 73, "user_calibrating": False},
            }
        ]
    )
    assert out["recovery_score"][0]["qty"] == 73.0
    assert out["recovery_calibrating"][0]["qty"] == 0.0
    assert out["heart_rate_variability"] == []
    assert out["blood_oxygen"] == []


def test_normalize_recovery_skips_unscored_records():
    out = normalize_recovery(
        [
            {
                "cycle_id": 1,
                "created_at": "2026-05-22T08:00:00Z",
                "score_state": "PENDING_SCORE",
                "score": None,
            },
            {
                "cycle_id": 2,
                "created_at": "2026-05-23T08:00:00Z",
                "score_state": "UNSCORABLE",
                "score": {"recovery_score": 50},
            },
        ]
    )
    for samples in out.values():
        assert samples == []


def test_normalize_sleep_emits_duration_efficiency_respiratory():
    out = normalize_sleep(
        [
            {
                "id": 1,
                "start": "2026-05-22T00:30:00Z",
                "end": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {
                    "stage_summary": {
                        "total_in_bed_time_milli": 27_000_000,  # 7.5 h
                        "total_awake_time_milli": 1_800_000,  # 0.5 h
                        "total_light_sleep_time_milli": 3_600_000,
                        "total_slow_wave_sleep_time_milli": 3_600_000,
                        "total_rem_sleep_time_milli": 3_600_000,
                        "disturbance_count": 4,
                    },
                    "sleep_efficiency_percentage": 96.5,
                    "respiratory_rate": 16.8,
                    "sleep_performance_percentage": 91.0,
                    "sleep_consistency_percentage": 88.0,
                    "sleep_needed": {"need_from_sleep_debt_milli": 1_800_000},
                },
            }
        ]
    )
    # 27_000_000 ms - 1_800_000 ms = 25_200_000 ms = 7.0 hours
    assert out["sleep_duration_hours"][0]["qty"] == 7.0
    # Dated at session end
    assert out["sleep_duration_hours"][0]["date"] == "2026-05-22T08:00:00Z"
    assert out["sleep_efficiency_percentage"][0]["qty"] == 96.5
    assert out["sleep_respiratory_rate"][0]["qty"] == 16.8
    assert out["sleep_performance_percentage"][0]["qty"] == 91.0
    assert out["sleep_consistency_percentage"][0]["qty"] == 88.0
    assert out["sleep_debt_minutes"][0]["qty"] == 30.0
    assert out["sleep_light_hours"][0]["qty"] == 1.0
    assert out["sleep_deep_hours"][0]["qty"] == 1.0
    assert out["sleep_rem_hours"][0]["qty"] == 1.0
    assert out["sleep_awake_hours"][0]["qty"] == 0.5
    assert out["sleep_disturbances"][0]["qty"] == 4.0


def test_normalize_sleep_handles_missing_stage_summary():
    """If stage_summary is missing, duration is skipped but efficiency
    + respiratory rate still emit if present.
    """
    out = normalize_sleep(
        [
            {
                "id": 1,
                "start": "2026-05-22T00:30:00Z",
                "end": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {
                    "sleep_efficiency_percentage": 88.0,
                },
            }
        ]
    )
    assert out["sleep_duration_hours"] == []
    assert out["sleep_efficiency_percentage"][0]["qty"] == 88.0


def test_normalize_workouts_matches_ios_emitted_shape():
    out = normalize_workouts(
        [
            {
                "id": 1,
                "start": "2026-05-22T18:00:00Z",
                "end": "2026-05-22T18:45:00Z",
                "sport_id": 0,  # Running
                "score_state": "SCORED",
                "score": {
                    "strain": 12.5,
                    "average_heart_rate": 145,
                    "max_heart_rate": 178,
                    "kilojoule": 1500.0,
                    "distance_meter": 6500.0,
                    "altitude_gain_meter": 123.4,
                    "zone_durations": {
                        "zone_one_milli": 600_000,
                        "zone_two_milli": 600_000,
                        "zone_three_milli": 600_000,
                        "zone_four_milli": 600_000,
                        "zone_five_milli": 600_000,
                    },
                },
            }
        ]
    )
    sample = out["workouts"][0]
    assert sample["name"] == "Running"
    assert sample["start"] == "2026-05-22T18:00:00Z"
    assert sample["end"] == "2026-05-22T18:45:00Z"
    assert sample["duration"] == 45 * 60  # 2700 s
    assert sample["avgHeartRate"] == 145
    assert sample["maxHeartRate"] == 178
    # 1500 kJ -> 358.51 kcal (rounded to 2 dp)
    assert sample["activeEnergy"] == 358.51
    assert sample["distance"] == 6500.0
    assert sample["source"] == SOURCE_TAG
    assert out["workout_altitude_gain_m"][0]["qty"] == 123.4
    assert out["workout_zone_1_minutes"][0]["qty"] == 10.0
    assert out["workout_zone_2_minutes"][0]["qty"] == 10.0
    assert out["workout_zone_3_minutes"][0]["qty"] == 10.0
    assert out["workout_zone_4_minutes"][0]["qty"] == 10.0
    assert out["workout_zone_5_minutes"][0]["qty"] == 10.0


def test_normalize_workouts_falls_back_for_unknown_sport_id():
    out = normalize_workouts(
        [
            {
                "id": 1,
                "start": "2026-05-22T18:00:00Z",
                "end": "2026-05-22T18:30:00Z",
                "sport_id": 9999,
                "score_state": "SCORED",
                "score": {},
            }
        ]
    )
    assert out["workouts"][0]["name"] == "sport_9999"


def test_normalize_workouts_skips_workouts_without_start_or_end():
    out = normalize_workouts(
        [
            {
                "id": 1,
                "sport_id": 0,
                "score_state": "SCORED",
                "score": {"strain": 5.0},
            }
        ]
    )
    assert out["workouts"] == []


def test_normalize_cycles_emits_strain_and_avg_heart_rate():
    out = normalize_cycles(
        [
            {
                "id": 1,
                "created_at": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {
                    "strain": 8.5,
                    "average_heart_rate": 75,
                    "kilojoule": 1000.0,
                },
            }
        ]
    )
    assert out["strain"] == [{"date": "2026-05-22T08:00:00Z", "qty": 8.5, "source": SOURCE_TAG}]
    # Cycle-derived HR is tagged so it does not collide with workout HR.
    assert "(cycle avg)" in out["heart_rate"][0]["source"]
    assert out["heart_rate"][0]["qty"] == 75.0
    assert out["cycle_calories"][0]["qty"] == 239.01


def test_normalize_cycles_falls_back_to_start_when_no_created_at():
    out = normalize_cycles(
        [
            {
                "id": 1,
                "start": "2026-05-22T00:00:00Z",
                "score_state": "SCORED",
                "score": {"strain": 4.2},
            }
        ]
    )
    assert out["strain"][0]["date"] == "2026-05-22T00:00:00Z"


def test_all_normalizers_return_empty_lists_for_empty_input():
    assert all(v == [] for v in normalize_body_measurement({}).values())
    assert all(v == [] for v in normalize_recovery([]).values())
    assert all(v == [] for v in normalize_sleep([]).values())
    assert normalize_workouts([])["workouts"] == []
    assert all(v == [] for v in normalize_cycles([]).values())
