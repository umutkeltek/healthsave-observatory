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
    normalize_cycles,
    normalize_recovery,
    normalize_sleep,
    normalize_workouts,
)


def test_normalize_recovery_emits_five_metrics_per_scored_item():
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
    for samples in out.values():
        assert all(s["source"] == SOURCE_TAG for s in samples)


def test_normalize_recovery_skips_missing_fields_silently():
    out = normalize_recovery(
        [
            {
                "cycle_id": 1,
                "created_at": "2026-05-22T08:00:00Z",
                "score_state": "SCORED",
                "score": {"recovery_score": 73},
            }
        ]
    )
    assert out["recovery_score"][0]["qty"] == 73.0
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
                    },
                    "sleep_efficiency_percentage": 96.5,
                    "respiratory_rate": 16.8,
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
                },
            }
        ]
    )
    assert out["strain"] == [{"date": "2026-05-22T08:00:00Z", "qty": 8.5, "source": SOURCE_TAG}]
    # Cycle-derived HR is tagged so it does not collide with workout HR.
    assert "(cycle avg)" in out["heart_rate"][0]["source"]
    assert out["heart_rate"][0]["qty"] == 75.0


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
    assert all(v == [] for v in normalize_recovery([]).values())
    assert all(v == [] for v in normalize_sleep([]).values())
    assert normalize_workouts([])["workouts"] == []
    assert all(v == [] for v in normalize_cycles([]).values())
