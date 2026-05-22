"""Zepp data-API payload → IngestStorage sample-shape normalizers.

H-normalize implementation (2026-05-22). Each normalizer takes the raw
fetcher payload (parsed JSON dict) and returns ``IngestStorage``-shape
rows the storage layer can write without further transformation.

Wire shapes were verified against live traffic — see
``tests/fixtures/zepp/data-*-shape.json`` and the H-revise probe log.
Specifically:

  * spo2 events carry the actual SpO2 percentage inside a
    JSON-encoded ``extra`` string with key ``spo2`` (and an
    ``spo2History[60]`` rolling window we ignore).
  * stress events carry per-minute readings inside a JSON-encoded
    ``data`` string (list of ``{time, value}``).
  * band_data summaries are base64-encoded JSON with ``stp.ttl``
    (steps), ``stp.dis`` (distance m), ``stp.cal`` (calories),
    ``slp`` (sleep segments), ``hr.maxHr`` (daily max HR).
  * heart_rate items shape is not directly captured (no data on the
    probed days). We accept the two common community shapes
    (``{time,value}`` and ``{timestamp,bpm}``) and surface unknowns
    via the normalizer's pass-through error count.

Every emitted sample carries ``source="Amazfit"`` so the source-aware
HA bridge and per-source dashboards split cleanly from Apple Watch /
Whoop entries.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("healthsave.plugins.amazfit.normalize")

SOURCE_TAG = "Amazfit"


def _ts_to_dt(value: int | float | str) -> datetime | None:
    """Best-effort milliseconds-or-seconds Unix → UTC datetime.

    Zepp's events tend to be in milliseconds; older personal_stack
    references used seconds. We disambiguate by magnitude — values
    above 2_000_000_000_000 (~Year 2033 in ms) are improbable as
    seconds, so we treat ≥1e12 as ms.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 1_000_000_000_000:
        return datetime.fromtimestamp(n / 1000, tz=UTC)
    return datetime.fromtimestamp(n, tz=UTC)


def _parse_json_string(blob: str | None) -> Any:
    """Parse a JSON-encoded string, returning ``None`` on failure."""
    if not blob or not isinstance(blob, str):
        return None
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_b64_json(blob: str | None) -> Any:
    """Decode a base64-encoded JSON string, returning ``None`` on failure."""
    if not blob or not isinstance(blob, str):
        return None
    try:
        decoded = base64.b64decode(blob + "==").decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    return _parse_json_string(decoded)


# ─── heart rate ─────────────────────────────────────────────────────────


def normalize_heart_rate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract per-minute heart-rate rows from a ``/users/<id>/heartRate``
    payload.

    Returns a list of ``{"date", "qty", "source"}`` quantity-sample rows
    keyed for the ``heart_rate`` dedicated table. The wire shape per
    item is one of:

      * ``{"time": <ms>, "value": <bpm>}``  (modern Zepp shape)
      * ``{"timestamp": <ms>, "bpm": <int>}``  (personal_stack 2024 hedge)

    We accept either and skip items missing both. Items with bpm ``<=0``
    are dropped silently (Zepp emits 0 for "no reading").
    """
    items = (payload or {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("time") or item.get("timestamp")
        bpm_raw = item.get("value") or item.get("bpm") or item.get("hr")
        if ts_raw is None or bpm_raw is None:
            continue
        ts = _ts_to_dt(ts_raw)
        if ts is None:
            continue
        try:
            bpm = int(bpm_raw)
        except (TypeError, ValueError):
            continue
        if bpm <= 0:
            continue
        rows.append({"date": ts.isoformat(), "qty": float(bpm), "source": SOURCE_TAG})
    return rows


# ─── SpO2 events ────────────────────────────────────────────────────────


def normalize_spo2_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract SpO2 percentages from a ``/users/<id>/events?eventType=blood_oxygen``
    payload.

    Each event carries a JSON-encoded ``extra`` field with ``spo2``
    (instantaneous reading, 0-100) plus ``spo2History`` (60-element
    rolling window we ignore — mostly zeroes when not actively
    measuring). The outer ``timestamp`` (ms) is used.
    """
    items = (payload or {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        extra = _parse_json_string(item.get("extra"))
        if not isinstance(extra, dict):
            continue
        spo2 = extra.get("spo2")
        if spo2 is None:
            continue
        try:
            spo2_pct = float(spo2)
        except (TypeError, ValueError):
            continue
        if not (0 < spo2_pct <= 100):
            continue
        ts = _ts_to_dt(item.get("timestamp"))
        if ts is None:
            continue
        rows.append({"date": ts.isoformat(), "qty": spo2_pct, "source": SOURCE_TAG})
    return rows


# ─── stress events ──────────────────────────────────────────────────────


def normalize_stress_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract per-minute stress readings from a
    ``/users/<id>/events?eventType=all_day_stress`` payload.

    The outer envelope carries daily aggregates (``avgStress``,
    ``minStress``, ``maxStress``, proportions); per-minute values
    live inside a JSON-encoded ``data`` field as a list of
    ``{time, value}`` records with ms timestamps and 0-100 scores.

    We emit one quantity_samples row per minute under the
    ``stress`` metric kind (no dedicated stress table exists).
    """
    items = (payload or {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        data = _parse_json_string(item.get("data"))
        if not isinstance(data, list):
            continue
        for sample in data:
            if not isinstance(sample, dict):
                continue
            ts = _ts_to_dt(sample.get("time"))
            if ts is None:
                continue
            try:
                value = float(sample["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= value <= 100):
                continue
            rows.append(
                {
                    "date": ts.isoformat(),
                    "qty": value,
                    "source": SOURCE_TAG,
                    "unit": "score",
                }
            )
    return rows


# ─── band data (daily activity + sleep summary) ─────────────────────────


def normalize_band_data(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extract daily activity + sleep + max-HR samples from a
    ``/v1/data/band_data.json`` summary payload.

    The payload is shaped ``{code, message, data: [<day records>]}``.
    Each day record has a ``date_time`` (``YYYY-MM-DD``) and a
    base64-encoded JSON ``summary`` blob with::

        {
          "stp": {"ttl": <steps>, "dis": <m>, "cal": <kcal>, ...},
          "slp": {"st": <unix-min>, "ed": <unix-min>, "dp": <min>, ...},
          "hr":  {"maxHr": {"hr": <bpm>, "ts": <unix>}},
          ...
        }

    Returns a dict with three keys:
      * ``daily_activity`` — one row per day with steps + distance + cal
      * ``sleep_sessions`` — one row per night when slp.st > 0
      * ``heart_rate`` — one row per day for the maxHr sample, if hr > 0
    """
    records = (payload or {}).get("data") or []
    daily_activity: list[dict[str, Any]] = []
    sleep_sessions: list[dict[str, Any]] = []
    heart_rate: list[dict[str, Any]] = []

    for rec in records:
        if not isinstance(rec, dict):
            continue
        date_str = rec.get("date_time")
        summary = _parse_b64_json(rec.get("summary"))
        if not isinstance(summary, dict):
            continue

        # Daily activity from stp.* — steps, distance (m), active cal.
        stp = summary.get("stp") or {}
        if isinstance(stp, dict) and date_str:
            steps = stp.get("ttl")
            dist = stp.get("dis")
            cal = stp.get("cal")
            if steps is not None or dist is not None or cal is not None:
                row: dict[str, Any] = {"date": date_str, "source": SOURCE_TAG}
                if steps is not None:
                    row["steps"] = int(steps)
                if dist is not None:
                    row["distance_m"] = float(dist)
                if cal is not None:
                    row["active_calories"] = float(cal)
                daily_activity.append(row)

        # Sleep — slp.st / slp.ed are minute-resolution Unix epochs in
        # the local timezone offset (slp.tz / outer tz=10800 seconds).
        # slp.dp = deep minutes, slp.lb = light minutes (community
        # convention; unverified for newer firmware).
        slp = summary.get("slp") or {}
        if isinstance(slp, dict):
            st_min = slp.get("st")
            ed_min = slp.get("ed")
            if (
                isinstance(st_min, int)
                and isinstance(ed_min, int)
                and st_min > 0
                and ed_min > st_min
            ):
                # Minute-resolution epoch — multiply by 60 for seconds.
                start_dt = datetime.fromtimestamp(st_min * 60, tz=UTC)
                end_dt = datetime.fromtimestamp(ed_min * 60, tz=UTC)
                session: dict[str, Any] = {
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "total_duration_ms": int((end_dt - start_dt).total_seconds() * 1000),
                    "source": SOURCE_TAG,
                }
                if isinstance(slp.get("dp"), int) and slp["dp"] > 0:
                    session["deep_ms"] = slp["dp"] * 60 * 1000
                if isinstance(slp.get("lb"), int) and slp["lb"] > 0:
                    session["light_ms"] = slp["lb"] * 60 * 1000
                if isinstance(slp.get("wk"), int) and slp["wk"] > 0:
                    session["awake_ms"] = slp["wk"] * 60 * 1000
                sleep_sessions.append(session)

        # Max-HR for the day — emit a single heart_rate row if non-zero.
        hr_block = summary.get("hr") or {}
        max_hr = (hr_block.get("maxHr") or {}) if isinstance(hr_block, dict) else {}
        if isinstance(max_hr, dict):
            hr_val = max_hr.get("hr")
            ts_val = max_hr.get("ts")
            if isinstance(hr_val, int) and hr_val > 0:
                ts = _ts_to_dt(ts_val) if ts_val else None
                if ts is None and date_str:
                    # Fallback: stamp at noon UTC of the date if no ts.
                    try:
                        ts = datetime.fromisoformat(f"{date_str}T12:00:00+00:00")
                    except ValueError:
                        ts = None
                if ts is not None:
                    heart_rate.append(
                        {
                            "date": ts.isoformat(),
                            "qty": float(hr_val),
                            "source": f"{SOURCE_TAG} (daily max)",
                        }
                    )

    return {
        "daily_activity": daily_activity,
        "sleep_sessions": sleep_sessions,
        "heart_rate": heart_rate,
    }


# ─── sport load ─────────────────────────────────────────────────────────


def normalize_sport_load(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract daily training-load aggregates from a SPORT_LOAD payload.

    Each item is one day with ``currnetDayTrainLoad`` (sic — Zepp's
    typo) plus ``wtlSum`` / optimal-range fields. We emit a single
    quantity-samples row per day under the ``training_load`` metric
    kind so it can sit alongside daily_activity in dashboards.

    Zepp's ``dayId`` is ``YYYYMMDD`` (no separator), and
    ``updateTime`` is ms.
    """
    items = (payload or {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        day_id = item.get("dayId")
        if not isinstance(day_id, str) or len(day_id) != 8 or not day_id.isdigit():
            continue
        try:
            iso = f"{day_id[0:4]}-{day_id[4:6]}-{day_id[6:8]}T12:00:00+00:00"
            ts = datetime.fromisoformat(iso)
        except ValueError:
            continue
        load = item.get("wtlSum")
        if load is None:
            load = item.get("currnetDayTrainLoad")
        if load is None:
            continue
        try:
            qty = float(load)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "date": ts.isoformat(),
                "qty": qty,
                "source": SOURCE_TAG,
                "unit": "training_load",
            }
        )
    return rows
