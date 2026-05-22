"""Tests for the Zepp data-API normalizers — H-normalize.

Fixtures below mirror the H-revise probe captures (with values left in
place for normalizer correctness — the captured-shape fixtures under
tests/fixtures/zepp/ keep only the structural shape; here we need
actual sample values to test extraction).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.amazfit.normalize import (  # noqa: E402
    SOURCE_TAG,
    normalize_band_data,
    normalize_heart_rate,
    normalize_spo2_events,
    normalize_sport_load,
    normalize_stress_events,
)

# ─── normalize_heart_rate ───────────────────────────────────────────────


def test_normalize_heart_rate_accepts_modern_time_value_shape():
    from datetime import UTC, datetime

    ts1, ts2 = 1779408000000, 1779408060000
    payload = {"items": [{"time": ts1, "value": 72}, {"time": ts2, "value": 68}]}
    rows = normalize_heart_rate(payload)
    assert len(rows) == 2
    assert rows[0]["qty"] == 72.0
    assert rows[0]["source"] == "Amazfit"
    assert rows[0]["date"] == datetime.fromtimestamp(ts1 / 1000, tz=UTC).isoformat()


def test_normalize_heart_rate_accepts_legacy_timestamp_bpm_shape():
    payload = {"items": [{"timestamp": 1779408000000, "bpm": 80}]}
    [row] = normalize_heart_rate(payload)
    assert row["qty"] == 80.0


def test_normalize_heart_rate_drops_zero_bpm_readings():
    """Zepp emits 0 when no reading is available — drop, don't store."""
    payload = {"items": [{"time": 1779408000000, "value": 0}, {"time": 1779408060000, "value": 70}]}
    rows = normalize_heart_rate(payload)
    assert len(rows) == 1
    assert rows[0]["qty"] == 70.0


def test_normalize_heart_rate_drops_items_missing_time_or_value():
    payload = {"items": [{"time": 1779408000000}, {"value": 70}, {}]}
    assert normalize_heart_rate(payload) == []


def test_normalize_heart_rate_empty_payload():
    assert normalize_heart_rate({}) == []
    assert normalize_heart_rate({"items": []}) == []


# ─── normalize_spo2_events ──────────────────────────────────────────────


def test_normalize_spo2_events_extracts_spo2_from_extra_json():
    extra = {
        "spo2": 99,
        "spo2History": [97, 99] + [0] * 58,
        "deviceId": "F4...",
        "isAuto": False,
    }
    payload = {
        "items": [
            {
                "eventType": "blood_oxygen",
                "extra": json.dumps(extra),
                "subType": "click",
                "timestamp": 1779322231000,
                "timezone": "Europe/Istanbul",
                "userId": "99999999",
            }
        ]
    }
    from datetime import UTC, datetime

    [row] = normalize_spo2_events(payload)
    assert row["qty"] == 99.0
    assert row["source"] == "Amazfit"
    assert row["date"] == datetime.fromtimestamp(1779322231, tz=UTC).isoformat()


def test_normalize_spo2_events_skips_items_with_unparseable_extra():
    payload = {"items": [{"extra": "not-json", "timestamp": 1779322231000}]}
    assert normalize_spo2_events(payload) == []


def test_normalize_spo2_events_skips_out_of_range():
    payload = {
        "items": [
            {"extra": json.dumps({"spo2": 0}), "timestamp": 1779322231000},
            {"extra": json.dumps({"spo2": 150}), "timestamp": 1779322231000},
            {"extra": json.dumps({"spo2": 97}), "timestamp": 1779322232000},
        ]
    }
    rows = normalize_spo2_events(payload)
    assert len(rows) == 1
    assert rows[0]["qty"] == 97.0


def test_normalize_spo2_events_empty():
    assert normalize_spo2_events({}) == []
    assert normalize_spo2_events({"items": []}) == []


# ─── normalize_stress_events ────────────────────────────────────────────


def test_normalize_stress_events_extracts_per_minute_values():
    data = [
        {"time": 1779399600000, "value": 48},
        {"time": 1779400500000, "value": 45},
        {"time": 1779401100000, "value": 44},
    ]
    payload = {
        "items": [
            {
                "avgStress": "24",
                "data": json.dumps(data),
                "eventType": "all_day_stress",
                "timestamp": 1779397200001,
                "userId": "99999999",
            }
        ]
    }
    rows = normalize_stress_events(payload)
    assert len(rows) == 3
    assert rows[0]["qty"] == 48.0
    assert rows[0]["source"] == "Amazfit"
    assert rows[0]["unit"] == "score"


def test_normalize_stress_events_skips_items_without_data_array():
    payload = {"items": [{"data": "not-json"}, {"data": json.dumps({"oops": True})}]}
    assert normalize_stress_events(payload) == []


def test_normalize_stress_events_drops_out_of_range_values():
    data = [{"time": 1779399600000, "value": -5}, {"time": 1779399700000, "value": 150}]
    payload = {"items": [{"data": json.dumps(data)}]}
    assert normalize_stress_events(payload) == []


def test_normalize_stress_events_empty():
    assert normalize_stress_events({}) == []


# ─── normalize_band_data ────────────────────────────────────────────────


def _band_data_payload(summary_obj: dict) -> dict:
    """Helper — wrap a summary dict in the band_data envelope (base64'd)."""
    encoded = base64.b64encode(json.dumps(summary_obj).encode("utf-8")).decode("ascii")
    return {
        "code": 1,
        "message": "success",
        "data": [
            {
                "uid": "99999999",
                "data_type": 0,
                "date_time": "2026-05-21",
                "source": 10289411,
                "summary": encoded,
                "device_id": "2445B531000074",
                "uuid": "EF25D064-B07C-49BE-8E42-0284DD7619B1",
            }
        ],
    }


def test_normalize_band_data_extracts_daily_activity():
    payload = _band_data_payload({"stp": {"ttl": 3786, "dis": 2772, "cal": 156, "runCal": 136}})
    out = normalize_band_data(payload)
    assert len(out["daily_activity"]) == 1
    row = out["daily_activity"][0]
    assert row["date"] == "2026-05-21"
    assert row["steps"] == 3786
    assert row["distance_m"] == 2772.0
    assert row["active_calories"] == 156.0
    assert row["source"] == "Amazfit"


def test_normalize_band_data_extracts_sleep_session_from_minute_epochs():
    # Minute-resolution unix → seconds = minute * 60. Use ~22:00→06:00.
    st_min = 29657115  # = 1779426900 unix = 2026-05-22T02:35:00Z
    ed_min = 29657580  # = 1779454800 unix = 2026-05-22T10:20:00Z
    payload = _band_data_payload(
        {"slp": {"st": st_min, "ed": ed_min, "dp": 120, "lb": 240, "wk": 30}}
    )
    out = normalize_band_data(payload)
    assert len(out["sleep_sessions"]) == 1
    s = out["sleep_sessions"][0]
    assert s["source"] == "Amazfit"
    assert s["deep_ms"] == 120 * 60 * 1000
    assert s["light_ms"] == 240 * 60 * 1000
    assert s["awake_ms"] == 30 * 60 * 1000
    assert s["total_duration_ms"] == (ed_min - st_min) * 60 * 1000


def test_normalize_band_data_extracts_max_hr_when_nonzero():
    payload = _band_data_payload({"hr": {"maxHr": {"hr": 142, "ts": 1779408000}}})
    out = normalize_band_data(payload)
    assert len(out["heart_rate"]) == 1
    assert out["heart_rate"][0]["qty"] == 142.0
    assert "daily max" in out["heart_rate"][0]["source"]


def test_normalize_band_data_skips_zero_max_hr():
    payload = _band_data_payload({"hr": {"maxHr": {"hr": 0, "ts": 0}}})
    out = normalize_band_data(payload)
    assert out["heart_rate"] == []


def test_normalize_band_data_handles_missing_summary():
    payload = {
        "data": [
            {"date_time": "2026-05-21", "summary": "not-base64"},
            {"date_time": "2026-05-20"},  # no summary at all
        ]
    }
    out = normalize_band_data(payload)
    assert out == {"daily_activity": [], "sleep_sessions": [], "heart_rate": []}


def test_normalize_band_data_empty():
    out = normalize_band_data({})
    assert out == {"daily_activity": [], "sleep_sessions": [], "heart_rate": []}


# ─── normalize_sport_load ───────────────────────────────────────────────


def test_normalize_sport_load_emits_one_row_per_day():
    payload = {
        "items": [
            {"dayId": "20260521", "wtlSum": 145, "currnetDayTrainLoad": 145},
            {"dayId": "20260520", "wtlSum": 0, "currnetDayTrainLoad": 0},
        ]
    }
    rows = normalize_sport_load(payload)
    assert len(rows) == 2
    assert rows[0]["qty"] == 145.0
    assert rows[1]["qty"] == 0.0
    assert rows[0]["unit"] == "training_load"
    assert rows[0]["source"] == "Amazfit"
    assert "2026-05-21T" in rows[0]["date"]


def test_normalize_sport_load_falls_back_to_currentDayTrainLoad():
    payload = {"items": [{"dayId": "20260521", "currnetDayTrainLoad": 99}]}
    [row] = normalize_sport_load(payload)
    assert row["qty"] == 99.0


def test_normalize_sport_load_skips_malformed_dayId():
    payload = {
        "items": [
            {"dayId": "bad-id", "wtlSum": 100},
            {"dayId": "2026-05-21", "wtlSum": 100},  # wrong separator
            {"dayId": "20260521", "wtlSum": 100},
        ]
    }
    rows = normalize_sport_load(payload)
    assert len(rows) == 1


def test_normalize_sport_load_empty():
    assert normalize_sport_load({}) == []


# ─── source tag ─────────────────────────────────────────────────────────


def test_all_normalizers_emit_amazfit_source_tag():
    assert SOURCE_TAG == "Amazfit"
