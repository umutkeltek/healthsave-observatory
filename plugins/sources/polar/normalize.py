"""Polar AccessLink exercise payload -> IngestStorage sample shapes."""

from __future__ import annotations

import re
from typing import Any

SOURCE_TAG = "Polar"
ORIGIN_PROVIDER = "polar-accesslink"

_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$"
)


def _duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return int(round(total))


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_exercises(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "workouts": [],
        "exercise_duration_seconds": [],
    }
    for item in items:
        exercise_id = item.get("id")
        start = item.get("start_time")
        duration = _duration_seconds(item.get("duration"))
        if not exercise_id or not start or duration is None:
            continue

        provider_device_id = item.get("device_id")
        base = {
            "source": SOURCE_TAG,
            "provider_object_id": str(exercise_id),
            "provider_device_id": str(provider_device_id) if provider_device_id else None,
            "origin_provider": ORIGIN_PROVIDER,
        }
        workout: dict[str, Any] = {
            "name": str(item.get("sport") or "Polar exercise"),
            "start": str(start),
            "duration": duration,
            **base,
        }
        if calories := _maybe_float(item.get("calories")):
            workout["activeEnergy"] = calories
        if distance := _maybe_float(item.get("distance")):
            workout["distance"] = distance
        heart_rate = item.get("heart_rate") or {}
        if isinstance(heart_rate, dict):
            if avg := _maybe_int(heart_rate.get("average")):
                workout["avgHeartRate"] = avg
            if max_hr := _maybe_int(heart_rate.get("maximum")):
                workout["maxHeartRate"] = max_hr

        out["workouts"].append({k: v for k, v in workout.items() if v is not None})
        out["exercise_duration_seconds"].append(
            {
                "date": str(start),
                "qty": float(duration),
                "unit": "s",
                **{k: v for k, v in base.items() if v is not None},
            }
        )
    return out
