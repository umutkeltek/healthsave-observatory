"""Polar AccessLink exercise payload -> IngestStorage sample shapes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from normalization import identity
from normalization.fusion import exact_ingest_key

from contracts._base import DEFAULT_WORKSPACE_ID, Provenance
from contracts.observation import Observation, build_dedup_key
from contracts.values import EventValue

SOURCE_TAG = "Polar"
ORIGIN_PROVIDER = "polar-accesslink"
VENDOR_FAMILY = "polar"
NORMALIZER_ID = "polar-accesslink"
NORMALIZER_VERSION = "0.1.0"
WORKOUT_SESSION_METRIC = "workout.session"

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


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _provider_subject_id(raw: Any, owner_id: UUID) -> str:
    if raw is None or str(raw).strip() == "":
        return str(owner_id)
    return str(raw)


def _provider_device_id(item: dict[str, Any]) -> str | None:
    value = item.get("device_id")
    return str(value) if value else None


def _activity_type(item: dict[str, Any]) -> str:
    return str(item.get("sport") or "OTHER")


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


def canonical_session_observations(
    items: list[dict[str, Any]],
    *,
    owner_id: UUID,
    provider_subject_id: str | int | None = None,
    captured_at: datetime | None = None,
) -> list[Observation]:
    """Normalize Polar exercises into canonical workout session observations."""

    source_id = identity.source_uuid(owner_id, ORIGIN_PROVIDER)
    subject_id = _provider_subject_id(provider_subject_id, owner_id)
    provenance = Provenance(
        source_plugin_id=ORIGIN_PROVIDER,
        sdk_version=NORMALIZER_VERSION,
        captured_at=captured_at or datetime.now(UTC),
    )
    observations: list[Observation] = []
    for item in items:
        exercise_id = item.get("id")
        start = _parse_ts(item.get("start_time"))
        duration = _duration_seconds(item.get("duration"))
        if not exercise_id or start is None or duration is None:
            continue

        end = start + timedelta(seconds=duration)
        provider_object_id = str(exercise_id)
        provider_device_id = _provider_device_id(item)
        activity_type = _activity_type(item)
        calories = _maybe_float(item.get("calories"))
        distance_m = _maybe_float(item.get("distance"))
        origin_key = identity.normalize_origin(provider_device_id or SOURCE_TAG)
        stream_id = identity.stream_id(owner_id, ORIGIN_PROVIDER, origin_key)
        summary: dict[str, Any] = {
            "vendor_family": VENDOR_FAMILY,
            "origin_provider": ORIGIN_PROVIDER,
            "provider_subject_id": subject_id,
            "provider_object_id": provider_object_id,
            "activity_type": activity_type,
            "duration_seconds": duration,
        }
        if provider_device_id:
            summary["provider_device_id"] = provider_device_id
        if calories is not None:
            summary["calories"] = calories
        if distance_m is not None:
            summary["distance_m"] = distance_m

        value = EventValue(
            type="event",
            label=activity_type,
            status="completed",
            summary=summary,
        )
        exact_key = exact_ingest_key(
            owner_id,
            source_id,
            "exercise",
            provider_object_id=provider_object_id,
        )
        observations.append(
            Observation(
                owner_id=owner_id,
                workspace_id=DEFAULT_WORKSPACE_ID,
                metric_id=WORKOUT_SESSION_METRIC,
                value=value,
                interval_start=start,
                interval_end=end,
                recorded_at=start,
                source_id=source_id,
                stream_id=stream_id,
                exact_ingest_key=exact_key,
                aggregation_scope="interval_component",
                source_record_uid=provider_object_id,
                provenance=provenance,
                normalizer_id=NORMALIZER_ID,
                normalizer_version=NORMALIZER_VERSION,
                dedup_key=build_dedup_key(
                    owner_id=owner_id,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    source_id=source_id,
                    metric_id=WORKOUT_SESSION_METRIC,
                    interval_start=start,
                    interval_end=end,
                    device_id=None,
                    source_record_uid=provider_object_id,
                    value_repr=value.model_dump_json(),
                ),
            )
        )
    return observations
