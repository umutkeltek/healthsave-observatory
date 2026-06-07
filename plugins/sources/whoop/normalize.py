"""Whoop payload -> IngestStorage sample-shape normalizers.

Each function takes the raw record list returned by the matching
:mod:`plugins.sources.whoop.fetch` function and returns a
``{metric_name: [sample_dict, ...]}`` mapping in the shape
:meth:`storage.ports.IngestStorage.ingest_metric` accepts.

Routing into Timescale tables — relies on the existing
``server.ingestion.mappers.DEDICATED_TABLES`` registry:

  * ``heart_rate_variability`` -> ``hrv`` table
  * ``blood_oxygen`` -> ``blood_oxygen`` table
  * ``body_temperature`` -> ``body_temperature`` table
  * ``heart_rate`` -> ``heart_rate`` table
  * ``workouts`` -> ``workouts`` table (via the dedicated workout
    handler that consumes ``name`` / ``start`` / ``end`` / ``duration``
    / ``avgHeartRate`` / ``maxHeartRate`` / ``activeEnergy`` / ``distance``)
  * everything else (``resting_heart_rate``, ``recovery_score``,
    ``recovery_calibrating``, ``strain``, ``cycle_calories``,
    ``sleep_duration_hours``, ``sleep_efficiency_percentage``,
    ``sleep_respiratory_rate``, ``sleep_performance_percentage``,
    ``sleep_consistency_percentage``, ``sleep_debt_minutes``,
    ``sleep_light_hours``, ``sleep_deep_hours``, ``sleep_rem_hours``,
    ``sleep_awake_hours``, ``sleep_disturbances``,
    ``workout_altitude_gain_m``, ``workout_zone_1_minutes``,
    ``workout_zone_2_minutes``, ``workout_zone_3_minutes``,
    ``workout_zone_4_minutes``, ``workout_zone_5_minutes``,
    ``height_meters``, ``weight_kg``, ``max_heart_rate``) ->
    ``quantity_samples`` catch-all, keyed on ``metric_name``.

Why Whoop sleep does NOT populate ``sleep_sessions``: that table
stores per-stage segments from HealthKit (start / end / stage value
per epoch). Whoop only exposes session-level aggregates
(``stage_summary``: total_light, total_rem, etc.) with no segment
timestamps; synthesizing segments would be lossy fiction. The
aggregates are the actual physical signal Whoop measures, so they
live where aggregates belong — ``quantity_samples``.

Every emitted sample carries ``source='Whoop'`` so multi-source
dashboards and the source-aware MQTT bridge can split it cleanly
from Apple Watch data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SOURCE_TAG = "Whoop"

# Whoop sport_id -> human name. The full table is in Whoop's developer
# docs; we ship the common ones and fall back to ``sport_<id>`` for
# unknown ids. Unknown ids are not an error path — the workouts table
# accepts any string in the ``name`` column.
_SPORT_NAMES: dict[int, str] = {
    -1: "Activity",
    0: "Running",
    1: "Cycling",
    16: "Baseball",
    17: "Basketball",
    18: "Rowing",
    22: "Golf",
    24: "Ice Hockey",
    27: "Rugby",
    29: "Skiing",
    30: "Soccer",
    33: "Swimming",
    34: "Tennis",
    36: "Volleyball",
    39: "Boxing",
    42: "Dance",
    43: "Pilates",
    44: "Yoga",
    45: "Weightlifting",
    47: "Cross Country Skiing",
    48: "Functional Fitness",
    52: "Hiking/Rucking",
    55: "Kayaking",
    56: "Martial Arts",
    57: "Mountain Biking",
    59: "Powerlifting",
    60: "Rock Climbing",
    63: "Walking",
    64: "Surfing",
    65: "Elliptical",
    66: "Stairmaster",
    70: "Meditation",
    71: "Other",
    82: "Pickleball",
    83: "Snowboarding",
}


def _sport_name(sport_id: int | None) -> str:
    if sport_id is None:
        return "workout"
    return _SPORT_NAMES.get(sport_id, f"sport_{sport_id}")


def _is_scored(item: dict[str, Any]) -> bool:
    """Whoop emits records with score_state in {SCORED, PENDING_SCORE,
    UNSCORABLE, NOT_SCORED}; we ingest only SCORED ones because the
    others have no usable values yet.
    """
    return item.get("score_state") == "SCORED" and item.get("score") is not None


def _duration_seconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((e - s).total_seconds())


def _kj_to_kcal(kj: float | None) -> float | None:
    """Whoop reports calories in kilojoules; the workouts table stores
    kilocalories. 1 kJ ~= 0.239006 kcal.
    """
    if kj is None:
        return None
    return round(kj * 0.239006, 2)


def normalize_body_measurement(item: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Single Whoop body-measurement object -> current body quantity samples."""
    out: dict[str, list[dict[str, Any]]] = {
        "height_meters": [],
        "weight_kg": [],
        "max_heart_rate": [],
    }
    if not item:
        return out
    ts = datetime.now(UTC).isoformat()
    if (h := item.get("height_meter")) is not None:
        out["height_meters"].append({"date": ts, "qty": float(h), "source": SOURCE_TAG})
    if (w := item.get("weight_kilogram")) is not None:
        out["weight_kg"].append({"date": ts, "qty": float(w), "source": SOURCE_TAG})
    if (mhr := item.get("max_heart_rate")) is not None:
        out["max_heart_rate"].append({"date": ts, "qty": float(mhr), "source": SOURCE_TAG})
    return out


def normalize_recovery(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One Whoop recovery -> quantity samples (HRV, SpO2, skin temp,
    RHR, recovery score, calibrating flag).
    """
    out: dict[str, list[dict[str, Any]]] = {
        "heart_rate_variability": [],
        "blood_oxygen": [],
        "body_temperature": [],
        "resting_heart_rate": [],
        "recovery_score": [],
        "recovery_calibrating": [],
    }
    for item in items:
        if not _is_scored(item):
            continue
        score = item["score"]
        ts = item.get("created_at")
        if not ts:
            continue

        if (hrv := score.get("hrv_rmssd_milli")) is not None:
            out["heart_rate_variability"].append(
                {"date": ts, "qty": float(hrv), "source": SOURCE_TAG}
            )
        if (spo2 := score.get("spo2_percentage")) is not None:
            out["blood_oxygen"].append({"date": ts, "qty": float(spo2), "source": SOURCE_TAG})
        if (temp := score.get("skin_temp_celsius")) is not None:
            out["body_temperature"].append({"date": ts, "qty": float(temp), "source": SOURCE_TAG})
        if (rhr := score.get("resting_heart_rate")) is not None:
            out["resting_heart_rate"].append({"date": ts, "qty": float(rhr), "source": SOURCE_TAG})
        if (rs := score.get("recovery_score")) is not None:
            out["recovery_score"].append({"date": ts, "qty": float(rs), "source": SOURCE_TAG})
        out["recovery_calibrating"].append(
            {
                "date": ts,
                "qty": 1.0 if score.get("user_calibrating") else 0.0,
                "source": SOURCE_TAG,
            }
        )

    return out


def normalize_sleep(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One Whoop sleep session -> aggregates as quantity samples.

    Dated at session end (when the night completes). The dedicated
    sleep_sessions table is for HealthKit per-segment data only —
    Whoop's session aggregates are not segments. See module docstring.
    """
    out: dict[str, list[dict[str, Any]]] = {
        "sleep_duration_hours": [],
        "sleep_efficiency_percentage": [],
        "sleep_respiratory_rate": [],
        "sleep_performance_percentage": [],
        "sleep_consistency_percentage": [],
        "sleep_debt_minutes": [],
        "sleep_light_hours": [],
        "sleep_deep_hours": [],
        "sleep_rem_hours": [],
        "sleep_awake_hours": [],
        "sleep_disturbances": [],
    }
    for item in items:
        if not _is_scored(item):
            continue
        score = item["score"]
        end = item.get("end")
        if not end:
            continue
        stage = score.get("stage_summary") or {}

        in_bed_ms = stage.get("total_in_bed_time_milli")
        awake_ms = stage.get("total_awake_time_milli", 0) or 0
        if in_bed_ms is not None:
            sleep_ms = max(0, int(in_bed_ms) - int(awake_ms))
            out["sleep_duration_hours"].append(
                {
                    "date": end,
                    "qty": round(sleep_ms / 3_600_000, 3),
                    "source": SOURCE_TAG,
                }
            )

        if (eff := score.get("sleep_efficiency_percentage")) is not None:
            out["sleep_efficiency_percentage"].append(
                {"date": end, "qty": float(eff), "source": SOURCE_TAG}
            )
        if (rr := score.get("respiratory_rate")) is not None:
            out["sleep_respiratory_rate"].append(
                {"date": end, "qty": float(rr), "source": SOURCE_TAG}
            )
        if (perf := score.get("sleep_performance_percentage")) is not None:
            out["sleep_performance_percentage"].append(
                {"date": end, "qty": float(perf), "source": SOURCE_TAG}
            )
        if (consistency := score.get("sleep_consistency_percentage")) is not None:
            out["sleep_consistency_percentage"].append(
                {"date": end, "qty": float(consistency), "source": SOURCE_TAG}
            )
        if (
            debt_ms := (score.get("sleep_needed") or {}).get("need_from_sleep_debt_milli")
        ) is not None:
            out["sleep_debt_minutes"].append(
                {"date": end, "qty": float(round(debt_ms / 60000, 3)), "source": SOURCE_TAG}
            )
        if (light_ms := stage.get("total_light_sleep_time_milli")) is not None:
            out["sleep_light_hours"].append(
                {"date": end, "qty": float(round(light_ms / 3_600_000, 3)), "source": SOURCE_TAG}
            )
        if (deep_ms := stage.get("total_slow_wave_sleep_time_milli")) is not None:
            out["sleep_deep_hours"].append(
                {"date": end, "qty": float(round(deep_ms / 3_600_000, 3)), "source": SOURCE_TAG}
            )
        if (rem_ms := stage.get("total_rem_sleep_time_milli")) is not None:
            out["sleep_rem_hours"].append(
                {"date": end, "qty": float(round(rem_ms / 3_600_000, 3)), "source": SOURCE_TAG}
            )
        if (awake_stage_ms := stage.get("total_awake_time_milli")) is not None:
            out["sleep_awake_hours"].append(
                {
                    "date": end,
                    "qty": float(round(awake_stage_ms / 3_600_000, 3)),
                    "source": SOURCE_TAG,
                }
            )
        if (disturbances := stage.get("disturbance_count")) is not None:
            out["sleep_disturbances"].append(
                {"date": end, "qty": float(disturbances), "source": SOURCE_TAG}
            )

    return out


def normalize_workouts(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One Whoop workout -> one workouts-table sample dict matching the
    iOS-emitted shape plus quantity samples for altitude gain and
    per-zone minutes.
    """
    samples: list[dict[str, Any]] = []
    out: dict[str, list[dict[str, Any]]] = {
        "workout_altitude_gain_m": [],
        "workout_zone_1_minutes": [],
        "workout_zone_2_minutes": [],
        "workout_zone_3_minutes": [],
        "workout_zone_4_minutes": [],
        "workout_zone_5_minutes": [],
    }
    for item in items:
        if not _is_scored(item):
            continue
        score = item["score"]
        start = item.get("start")
        end = item.get("end")
        if not start or not end:
            continue

        sample: dict[str, Any] = {
            "name": _sport_name(item.get("sport_id")),
            "start": start,
            "end": end,
            "source": SOURCE_TAG,
        }
        if (duration := _duration_seconds(start, end)) is not None:
            sample["duration"] = duration
        if (avg_hr := score.get("average_heart_rate")) is not None:
            sample["avgHeartRate"] = int(avg_hr)
        if (max_hr := score.get("max_heart_rate")) is not None:
            sample["maxHeartRate"] = int(max_hr)
        if (kcal := _kj_to_kcal(score.get("kilojoule"))) is not None:
            sample["activeEnergy"] = kcal
        if (dist := score.get("distance_meter")) is not None:
            sample["distance"] = float(dist)
        if (altitude := score.get("altitude_gain_meter")) is not None:
            out["workout_altitude_gain_m"].append(
                {"date": start, "qty": float(altitude), "source": SOURCE_TAG}
            )

        zones = score.get("zone_durations") or score.get("zone_duration") or {}
        if (zone_1 := zones.get("zone_one_milli")) is not None:
            out["workout_zone_1_minutes"].append(
                {"date": start, "qty": float(round(zone_1 / 60000, 3)), "source": SOURCE_TAG}
            )
        if (zone_2 := zones.get("zone_two_milli")) is not None:
            out["workout_zone_2_minutes"].append(
                {"date": start, "qty": float(round(zone_2 / 60000, 3)), "source": SOURCE_TAG}
            )
        if (zone_3 := zones.get("zone_three_milli")) is not None:
            out["workout_zone_3_minutes"].append(
                {"date": start, "qty": float(round(zone_3 / 60000, 3)), "source": SOURCE_TAG}
            )
        if (zone_4 := zones.get("zone_four_milli")) is not None:
            out["workout_zone_4_minutes"].append(
                {"date": start, "qty": float(round(zone_4 / 60000, 3)), "source": SOURCE_TAG}
            )
        if (zone_5 := zones.get("zone_five_milli")) is not None:
            out["workout_zone_5_minutes"].append(
                {"date": start, "qty": float(round(zone_5 / 60000, 3)), "source": SOURCE_TAG}
            )

        samples.append(sample)

    return {"workouts": samples, **out}


def normalize_cycles(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One Whoop cycle -> daily strain + calories (quantity_samples)
    and average HR (heart_rate table, tagged source as
    ``Whoop (cycle avg)`` so it does not collide with workout-derived
    HR samples at the same timestamp).
    """
    out: dict[str, list[dict[str, Any]]] = {
        "strain": [],
        "heart_rate": [],
        "cycle_calories": [],
    }
    for item in items:
        if not _is_scored(item):
            continue
        score = item["score"]
        ts = item.get("created_at") or item.get("start")
        if not ts:
            continue
        if (strain := score.get("strain")) is not None:
            out["strain"].append({"date": ts, "qty": float(strain), "source": SOURCE_TAG})
        if (avg_hr := score.get("average_heart_rate")) is not None:
            out["heart_rate"].append(
                {"date": ts, "qty": float(avg_hr), "source": f"{SOURCE_TAG} (cycle avg)"}
            )
        if (cal := _kj_to_kcal(score.get("kilojoule"))) is not None:
            out["cycle_calories"].append({"date": ts, "qty": float(cal), "source": SOURCE_TAG})

    return out
