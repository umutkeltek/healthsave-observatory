"""Polar AccessLink exercise payload normalizers."""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.polar.normalize import SOURCE_TAG, normalize_exercises  # noqa: E402


def test_normalize_exercises_emits_workout_and_duration_projection():
    out = normalize_exercises(
        [
            {
                "id": "2AC312F",
                "device_id": "1111AAAA",
                "start_time": "2008-10-13T10:40:02",
                "duration": "PT2H44M",
                "calories": 530,
                "distance": 1600,
                "heart_rate": {"average": 129, "maximum": 147},
                "sport": "RUNNING",
            }
        ]
    )

    workout = out["workouts"][0]
    assert workout == {
        "name": "RUNNING",
        "start": "2008-10-13T10:40:02",
        "duration": 9840,
        "activeEnergy": 530.0,
        "distance": 1600.0,
        "avgHeartRate": 129,
        "maxHeartRate": 147,
        "source": SOURCE_TAG,
        "provider_object_id": "2AC312F",
        "provider_device_id": "1111AAAA",
        "origin_provider": "polar-accesslink",
    }
    assert out["exercise_duration_seconds"] == [
        {
            "date": "2008-10-13T10:40:02",
            "qty": 9840.0,
            "unit": "s",
            "source": SOURCE_TAG,
            "provider_object_id": "2AC312F",
            "provider_device_id": "1111AAAA",
            "origin_provider": "polar-accesslink",
        }
    ]


def test_normalize_exercises_skips_rows_without_id_start_or_duration():
    out = normalize_exercises(
        [
            {"id": "E1", "start_time": "2026-06-01T10:00:00", "duration": None},
            {"id": "E2", "duration": "PT30M"},
            {"start_time": "2026-06-01T10:00:00", "duration": "PT30M"},
        ]
    )

    assert out == {"workouts": [], "exercise_duration_seconds": []}


def test_normalize_exercises_handles_hour_minute_second_duration():
    out = normalize_exercises(
        [{"id": "E1", "start_time": "2026-06-01T10:00:00", "duration": "PT1H2M3S"}]
    )

    assert out["workouts"][0]["duration"] == 3723
