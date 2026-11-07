"""MCP read server: every tool against a fake Observatory (packages/mcp).

Series payloads are produced by the API's own serializer (``_point_dicts`` on
``SeriesPoint``), so a change in the wire shape the server sends breaks these
tests, not a person's answers. The synthetic year mirrors the e2e seed: a
watch all year, a ring from April 10, nothing at all August 3-11.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from healthsave_mcp import tools
from healthsave_mcp.client import Config, ObservatoryClient
from server.api.v2_metrics import _point_dicts
from storage.timescale.observations import SeriesPoint

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
CLOCK = lambda: NOW  # noqa: E731
START = date(2026, 1, 1)
OFF = (date(2026, 8, 3), date(2026, 8, 11))
RING_FROM = date(2026, 4, 10)
WATCH, RING, PHONE = "stream-watch", "stream-ring", "stream-phone-all"
SETTINGS = {"time_zone": "UTC", "day_boundary_minutes": 0, "day_boundary": "00:00"}


def _days() -> list[date]:
    last = NOW.date() - timedelta(days=1)
    return [START + timedelta(days=i) for i in range((last - START).days + 1)]


def _off(day: date) -> bool:
    return OFF[0] <= day <= OFF[1]


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _sp(t, value=None, *, end=None, code=None, unit=None, stream=WATCH, scope="interval_component"):
    return SeriesPoint(
        t=t,
        interval_end=end or t,
        value=value,
        code=code,
        unit=unit,
        source_id="apple_health",
        confidence=None,
        stream_id=stream,
        aggregation_scope=scope,
    )


def _sleep_points() -> list[dict]:
    rng = random.Random(7)
    out = []
    for day in _days():
        if _off(day):
            continue
        t = _at(day, 22, 40 + rng.randint(-10, 10))
        for code, minutes in (
            ("Core", 110),
            ("Deep", 60),
            ("REM", 80),
            ("Awake", 6),
            ("Core", 170),
        ):
            end = t + timedelta(minutes=minutes)
            out.append(_sp(t, end=end, code=code))
            t = end
    return _point_dicts(out)


def _daily(metric: str) -> list[dict]:
    rng = random.Random(metric)
    out = []
    for day in _days() + [NOW.date()]:
        if _off(day):
            continue
        partial = day == NOW.date()
        if metric == "activity.steps":
            out.append(
                _sp(
                    _at(day, 0),
                    3100 if partial else 8000 + rng.randint(-1500, 1500),
                    end=_at(day, 0) + timedelta(days=1),
                    unit="count",
                    stream=PHONE,
                    scope="owner_all_source_day_total",
                )
            )
        elif metric == "activity.active_energy":
            out.append(
                _sp(
                    _at(day, 0),
                    120 if partial else 450 + rng.randint(-60, 60),
                    end=_at(day, 0) + timedelta(days=1),
                    unit="kcal",
                    stream=PHONE,
                    scope="owner_all_source_day_total",
                )
            )
        elif metric == "vital.resting_heart_rate" and not partial:
            out.append(_sp(_at(day, 6), 56 + rng.random(), unit="count/min", stream=WATCH))
            if day >= RING_FROM:
                out.append(_sp(_at(day, 6, 30), 53 + rng.random(), unit="count/min", stream=RING))
        elif metric == "vital.hrv_sdnn" and not partial:
            out.append(_sp(_at(day, 5), 50 + rng.random() * 4, unit="ms", stream=WATCH))
    if metric == "vital.resting_heart_rate":
        out.append(_sp(_at(NOW.date(), 6), 63, unit="count/min", stream=WATCH))  # above usual
    return _point_dicts(out)


SERIES = {
    "sleep.stage": _sleep_points,
    "activity.steps": lambda: _daily("activity.steps"),
    "activity.active_energy": lambda: _daily("activity.active_energy"),
    "vital.resting_heart_rate": lambda: _daily("vital.resting_heart_rate"),
    "vital.hrv_sdnn": lambda: _daily("vital.hrv_sdnn"),
}
RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30, "90d": 90, "1y": 365}
CATALOG = [
    {
        "id": "vital.resting_heart_rate",
        "display_name": "Resting Heart Rate",
        "category": "vital",
        "value_type": "quantity",
        "canonical_unit": "bpm",
    },
    {
        "id": "vital.hrv_sdnn",
        "display_name": "Heart Rate Variability (SDNN)",
        "category": "vital",
        "value_type": "quantity",
        "canonical_unit": "ms",
    },
    {
        "id": "activity.steps",
        "display_name": "Steps",
        "category": "activity",
        "value_type": "quantity",
        "canonical_unit": "count",
    },
    {
        "id": "sleep.stage",
        "display_name": "Sleep Stage",
        "category": "sleep",
        "value_type": "category",
        "canonical_unit": None,
    },
]
FINDINGS = {
    "findings": [
        {
            "id": 7,
            "finding_type": "recovery_score",
            "metric": "recovery",
            "severity": "info",
            "structured_data": {
                "score": 71,
                "method": "v1",
                "contributors": {"hrv_vs_baseline_pct": 4.0, "rhr_vs_baseline_pct": -2.0},
                "missing_inputs": [],
            },
            "created_at": "2026-11-07T07:05:00Z",
        },
        {
            "id": 6,
            "finding_type": "anomaly",
            "metric": "vital.resting_heart_rate",
            "severity": "notable",
            "structured_data": {"z": 2.712345678, "baseline_days": list(range(40))},
            "created_at": "2026-10-25T07:00:00Z",
        },
    ],
    "count": 2,
}
LAB_RESULT = {
    "id": "r1",
    "specimen_at": "2026-09-08T05:50:00Z",
    "value": 24.0,
    "comparator": None,
    "unit": "ng/mL",
    "display_unit": "ng/mL",
    "reference_low": 30.0,
    "reference_high": 400.0,
    "lab": "Northfield Diagnostics",
    "band": "below",
    "band_fraction": -0.0162,
}
LABS = {
    "markers": [
        {
            "loinc": "2276-4",
            "name": "Ferritin",
            "unit": "ng/mL",
            "display_unit": "ng/mL",
            "result_count": 1,
            "lab_count": 1,
            "results": [LAB_RESULT],
            "assessment": {"latest_band": "below", "change_withheld": "first result"},
            "gap_count": 0,
        }
    ],
    "count": 1,
    "result_count": 1,
}
YEAR = {
    "year": 2026,
    "owner_id": "00000000-0000-0000-0000-000000000001",
    "time_zone": "UTC",
    "day_boundary": "00:00",
    "window_start": "2026-01-01",
    "window_end": "2026-11-07",
    "days_in_window": 311,
    "days_with_data": 302,
    "mask": "1" * 311,
    "day_family_counts": [3] * 311,
    "gaps": [{"start": "2026-08-03", "end": "2026-08-11", "days": 9, "kind": "inside"}],
    "longest_inside_gap": 9,
    "months": [
        {
            "month": 4,
            "days": 30,
            "days_with_data": 30,
            "coverage": 1.0,
            "families": ["heart", "sleep"],
            "source_ids": [WATCH, RING],
            "first_seen_ids": [RING],
            "last_seen_ids": [],
            "confidence": "ok",
        }
    ],
    "families": [
        {
            "id": "sleep",
            "label": "Sleep",
            "metric_ids": ["sleep.stage"],
            "days_with_data": 300,
            "days_without_data": 11,
            "first_day": "2026-01-01",
            "last_day": "2026-11-06",
            "mask": "1" * 311,
            "longest_inside_gap": 9,
            "gaps": [{"start": "2026-08-03", "end": "2026-08-11", "days": 9, "kind": "inside"}],
            "confidence": "ok",
        }
    ],
    "sources": [
        {
            "stream_id": WATCH,
            "label": "Apple Watch",
            "first_day": "2026-01-01",
            "last_day": "2026-11-06",
            "days_with_data": 302,
            "families": ["heart", "sleep"],
            "new_this_year": False,
            "stopped_this_year": False,
        },
        {
            "stream_id": RING,
            "label": "Oura Ring",
            "first_day": "2026-04-10",
            "last_day": "2026-11-06",
            "days_with_data": 200,
            "families": ["heart"],
            "new_this_year": True,
            "stopped_this_year": False,
        },
    ],
    "device_changes": [
        {"day": "2026-04-10", "kind": "first_seen", "stream_id": RING, "label": "Oura Ring"}
    ],
    "headlines": [
        {
            "id": "resting_heart_rate",
            "label": "Resting heart rate",
            "value": 56.0,
            "unit": "bpm",
            "source_label": "Apple Watch",
            "basis": "median_one_source",
            "confidence": "ok",
        }
    ],
    "withheld": [],
    "limitations": [{"code": "partial_year", "day": "2026-11-07", "count": None}],
    "confidence": "ok",
    "generated_at": "2026-11-07T02:00:00Z",
}


class FakeObservatory:
    """Answers the read API; ``deny`` lists paths that answer 403 (a narrower key)."""

    def __init__(self, *, deny: tuple[str, ...] = (), cap: int | None = None) -> None:
        self.deny = deny
        self.cap = cap
        self.requests: list[httpx.Request] = []

    def _series(self, metric: str, range_: str) -> list[dict]:
        points = SERIES.get(metric, list)()
        since = NOW - timedelta(days=RANGE_DAYS.get(range_, 3650))
        points = [p for p in points if datetime.fromisoformat(p["t"]) >= since]
        if self.cap is not None:
            points = points[-self.cap :]
        return points

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, q = request.url.path, request.url.params
        if any(path.startswith(d) for d in self.deny):
            return httpx.Response(
                403, json={"detail": f"api_key_scope: read key cannot call GET {path}"}
            )
        if path == "/api/v2/settings/analytical-time":
            return httpx.Response(200, json=SETTINGS)
        if path == "/api/v2/metrics":
            return httpx.Response(200, json=CATALOG)
        if path.startswith("/api/v2/metrics/") and path.endswith("/series"):
            metric = path.split("/")[4]
            return httpx.Response(
                200,
                json={
                    "metric": {"id": metric},
                    "range": q["range"],
                    "points": self._series(metric, q["range"]),
                },
            )
        if path == "/api/v2/series":
            ids = q["ids"].split(",")
            return httpx.Response(
                200,
                json={
                    "range": q["range"],
                    "series": [
                        {"metric": {"id": i}, "points": self._series(i, q["range"])} for i in ids
                    ],
                },
            )
        if path == "/api/v2/streams":
            return httpx.Response(
                200,
                json={
                    "streams": [
                        {"id": WATCH, "device_label": "Apple Watch"},
                        {"id": RING, "device_label": "Oura Ring"},
                        {"id": PHONE, "device_label": "iPhone"},
                    ]
                },
            )
        if path == "/api/v2/insights/findings":
            rows = [
                f
                for f in FINDINGS["findings"]
                if not q.get("type") or f["finding_type"] == q["type"]
            ]
            return httpx.Response(
                200, json={"findings": rows[: int(q.get("limit", 50))], "count": len(rows)}
            )
        if path == "/api/v2/insights/correlations":
            return httpx.Response(
                200, json={"correlations": [{"a": "sleep", "b": "hrv", "r": 0.41234567, "n": 90}]}
            )
        if path == "/api/v2/labs":
            return httpx.Response(200, json=LABS)
        if path == "/api/v2/labs/2276-4":
            return httpx.Response(
                200,
                json={
                    **LABS["markers"][0],
                    "results": [LAB_RESULT] * 25,
                    "gaps": [],
                    "cross_match": {"card": None, "reason": "coverage"},
                },
            )
        if path.startswith("/api/v2/labs/"):
            return httpx.Response(404, json={"detail": "no results"})
        if path == "/api/v2/year/2026":
            return httpx.Response(200, json=YEAR)
        if path == "/api/v2/year/2031":
            return httpx.Response(422, json={"detail": "year 2031 has not started"})
        if path == "/api/v2/readiness":
            return httpx.Response(
                200,
                json={
                    "last_observation_at": "2026-11-07T06:00:00Z",
                    "last_ingested_at": "2026-11-07T06:05:00Z",
                    "metrics": [
                        {
                            "metric_id": "sleep.stage",
                            "display_name": "Sleep",
                            "days_with_data": 302,
                            "observation_count": 1510,
                            "first_observation_at": "2026-01-01T22:30:00Z",
                            "last_observation_at": "2026-11-07T05:00:00Z",
                        },
                        {
                            "metric_id": "vital.resting_heart_rate",
                            "display_name": "Resting HR",
                            "days_with_data": 302,
                            "observation_count": 500,
                            "first_observation_at": "2026-01-01T06:00:00Z",
                            "last_observation_at": "2026-11-07T06:00:00Z",
                        },
                        {
                            "metric_id": "vital.blood_glucose",
                            "display_name": "Blood Glucose",
                            "days_with_data": 0,
                            "observation_count": 0,
                        },
                    ],
                },
            )
        if path == "/api/v2/devices":
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {
                            "device_label": "Apple Watch",
                            "first_seen_at": "2026-01-01T00:00:00Z",
                            "last_seen_at": "2026-11-07T06:00:00Z",
                        }
                    ]
                },
            )
        if path == "/api/v2/sync/runs/latest":
            return httpx.Response(
                200,
                json={
                    "completed_at": "2026-11-07T06:05:00Z",
                    "status": "ok",
                    "records_received": 120,
                },
            )
        return httpx.Response(404, json={"detail": "Not Found"})

    def client(self) -> ObservatoryClient:
        return ObservatoryClient(
            Config("http://obs.test:8000", "k"), transport=httpx.MockTransport(self.handler)
        )


def _assert_summary_only(result: dict[str, Any], fake: FakeObservatory) -> None:
    """Every tool: the envelope, GETs to the one host, no raw readings out."""

    assert {"tool", "limitations", "read_from", "note"} <= set(result)
    assert all(r.method == "GET" and r.url.host == "obs.test" for r in fake.requests)
    text = json.dumps(result)
    assert "interval_end" not in text and '"points"' not in text and "semantic_key" not in text
    assert len(text) < 40_000, f"{result['tool']} returned {len(text)} bytes"


# ─── sleep ─────────────────────────────────────────────────────────────


async def test_sleep_this_year_answers_how_did_i_sleep_this_year() -> None:
    fake = FakeObservatory()
    result = await tools.sleep_summary(fake.client(), "this_year", clock=CLOCK)
    _assert_summary_only(result, fake)
    assert result["window"]["from"] == "2026-01-01" and result["window"]["to"] == "2026-11-07"
    summary = result["summary"]
    assert summary["nights"] == len(_days()) - 9
    assert 7.0 <= summary["asleep_h"]["median"] <= 7.2  # 420 of 426 minutes; awake left out
    assert summary["typical_wake"].startswith("05:")
    assert [m["month"] for m in result["months"]][:2] == ["2026-01", "2026-02"]
    assert result["nights_without_data"]["runs"] == [
        {"from": "2026-08-03", "to": "2026-08-11", "days": 9}
    ]
    assert len(result["nights"]) == tools.DETAIL_LIMIT
    assert "GET /api/v2/metrics/sleep.stage/series?range=1y" in result["read_from"]
    assert result["units"]["asleep_h"].startswith("hours asleep")


async def test_last_night_is_one_night_with_its_stages() -> None:
    result = await tools.sleep_summary(FakeObservatory().client(), "last_night", clock=CLOCK)
    [night] = result["nights"]
    assert night["night_of"] == "2026-11-06"
    assert night["stage_minutes"]["deep"] == 60 and night["stage_minutes"]["awake"] == 6


async def test_sleep_says_when_days_are_grouped_in_utc_for_a_narrow_key() -> None:
    fake = FakeObservatory(deny=("/api/v2/settings",))
    result = await tools.sleep_summary(fake.client(), "last_7_nights", clock=CLOCK)
    assert [lim["code"] for lim in result["limitations"]] == ["time_basis_utc"]
    assert result["summary"]["nights"] == 7


async def test_a_window_the_server_cut_is_named_with_its_real_start(monkeypatch) -> None:
    # A real year of watch sleep is ~12k stage readings, over the server's 5,000.
    monkeypatch.setattr(tools.derive, "SERVER_POINT_CAP", 1000)
    result = await tools.sleep_summary(FakeObservatory(cap=1000).client(), "this_year", clock=CLOCK)
    [cut] = [lim for lim in result["limitations"] if lim["code"] == "window_cut"]
    assert "1,000 readings" in cut["detail"] and "sleep before 2026-04-" in cut["detail"]
    first = result["window"]
    assert result["summary"]["nights"] < len(_days()) - 9
    assert first["evenings_counted"] < len(_days())


async def test_an_unknown_period_is_a_plain_refusal() -> None:
    with pytest.raises(ValueError, match="period must be one of"):
        await tools.sleep_summary(FakeObservatory().client(), "forever", clock=CLOCK)


# ─── activity ──────────────────────────────────────────────────────────


async def test_activity_last_30_days_keeps_today_apart_and_gives_units() -> None:
    fake = FakeObservatory()
    result = await tools.activity_summary(fake.client(), "last_30_days", clock=CLOCK)
    _assert_summary_only(result, fake)
    steps = result["totals"]["steps"]
    assert steps["days_with_data"] == 30
    assert 6500 <= steps["per_day"]["mean"] <= 9500
    assert steps["today_so_far"] == 3100 and steps["usual_full_day"]["days"] == 28
    assert result["units"]["steps"] == "steps per day"
    assert "today_in_progress" in [lim["code"] for lim in result["limitations"]]
    assert result["days"][-1]["date"] == "2026-11-07" and len(result["days"]) == tools.DETAIL_LIMIT


async def test_activity_this_year_is_monthly() -> None:
    result = await tools.activity_summary(FakeObservatory().client(), "this_year", clock=CLOCK)
    august = next(m for m in result["months"] if m["month"] == "2026-08")
    assert august["days_with_data"] == 31 - 9


# ─── today ─────────────────────────────────────────────────────────────


async def test_today_compares_each_reading_with_the_same_sources_usual() -> None:
    fake = FakeObservatory()
    result = await tools.today_vs_usual(fake.client(), clock=CLOCK)
    _assert_summary_only(result, fake)
    rhr = next(r for r in result["readings"] if r["metric"] == "vital.resting_heart_rate")
    assert rhr["value"] == 63 and rhr["place"] == "above" and rhr["unit"] == "bpm"
    assert rhr["source"] == "Apple Watch"
    assert rhr["other_sources_not_mixed_in"] == ["Oura Ring"]
    assert 56 <= rhr["usual"]["median"] <= 57  # the watch's own range, not pooled with the ring
    assert result["last_night"]["night_of"] == "2026-11-06"
    assert result["recovery"]["score"] == 71
    steps = next(t for t in result["totals"] if t["metric"] == "activity.steps")
    assert steps["today_so_far"] == 3100 and steps["yesterday"] is not None


async def test_today_without_findings_access_says_so_and_still_answers() -> None:
    fake = FakeObservatory(deny=("/api/v2/insights", "/api/v2/settings"))
    result = await tools.today_vs_usual(fake.client(), clock=CLOCK)
    codes = [lim["code"] for lim in result["limitations"]]
    assert "key_scope" in codes and "time_basis_utc" in codes
    assert result["recovery"] is None and result["readings"]


# ─── one metric ────────────────────────────────────────────────────────


async def test_metric_trend_is_daily_for_short_and_monthly_for_long_periods() -> None:
    fake = FakeObservatory()
    short = await tools.metric_trend(fake.client(), "vital.hrv_sdnn", "last_30_days", clock=CLOCK)
    _assert_summary_only(short, fake)
    assert short["unit"] == "ms" and short["source"] == "Apple Watch"
    assert len(short["days"]) == 30 and "months" not in short
    year = await tools.metric_trend(
        FakeObservatory().client(), "vital.resting_heart_rate", "this_year", clock=CLOCK
    )
    assert year["months"][0]["month"] == "2026-01" and len(year["days"]) == tools.DETAIL_LIMIT
    assert year["other_sources_not_mixed_in"] == ["Oura Ring"]


async def test_metric_trend_reads_totals_as_one_total_per_day() -> None:
    result = await tools.metric_trend(
        FakeObservatory().client(), "activity.steps", "last_7_days", clock=CLOCK
    )
    assert result["per_day"].startswith("one total per day")
    assert result["days"][-1] == {"date": "2026-11-07", "total": 3100}


async def test_metric_trend_refuses_unknown_and_non_numeric_metrics() -> None:
    with pytest.raises(ValueError, match="did you mean vital.hrv_sdnn"):
        await tools.metric_trend(FakeObservatory().client(), "vital.hrv", clock=CLOCK)
    with pytest.raises(ValueError, match="sleep_summary"):
        await tools.metric_trend(FakeObservatory().client(), "sleep.stage", clock=CLOCK)


# ─── findings, labs, year, overview ────────────────────────────────────


async def test_findings_are_compacted_and_correlations_come_along() -> None:
    fake = FakeObservatory()
    result = await tools.findings(fake.client(), clock=CLOCK)
    _assert_summary_only(result, fake)
    anomaly = next(f for f in result["findings"] if f["type"] == "anomaly")
    assert anomaly["data"]["z"] == 2.7123
    assert anomaly["data"]["baseline_days"][-1] == "... 28 more"
    assert result["correlations"][0]["r"] == 0.4123
    assert (await tools.findings(fake.client(), limit=500, clock=CLOCK))["count"] == 2


async def test_findings_with_a_participant_key_explain_instead_of_failing() -> None:
    result = await tools.findings(FakeObservatory(deny=("/api/v2/insights",)).client(), clock=CLOCK)
    assert result["findings"] == [] and result["limitations"][0]["code"] == "key_scope"
    assert "healthsave mcp key" in result["limitations"][0]["detail"]


async def test_lab_results_list_and_one_marker() -> None:
    fake = FakeObservatory()
    listed = await tools.lab_results(fake.client(), clock=CLOCK)
    _assert_summary_only(listed, fake)
    [ferritin] = listed["markers"]
    assert ferritin["latest"] == {
        "date": "2026-09-08",
        "value": 24.0,
        "comparator": None,
        "unit": "ng/mL",
        "lab": "Northfield Diagnostics",
        "lab_range": [30.0, 400.0],
        "band": "below",
    }
    one = await tools.lab_results(fake.client(), "2276-4", clock=CLOCK)
    assert len(one["marker"]["results"]) == 20
    assert [lim["code"] for lim in one["limitations"]] == ["list_cut"]
    missing = await tools.lab_results(fake.client(), "1234-5", clock=CLOCK)
    assert missing["limitations"][0]["code"] == "no_data"


async def test_year_in_health_drops_the_day_masks_and_names_sources() -> None:
    fake = FakeObservatory()
    result = await tools.year_in_health(fake.client(), clock=CLOCK)
    _assert_summary_only(result, fake)
    text = json.dumps(result)
    assert '"mask"' not in text and "day_family_counts" not in text
    assert result["months"][0]["sources"] == ["Apple Watch", "Oura Ring"]
    assert result["months"][0]["first_seen"] == ["Oura Ring"]
    assert result["device_changes"] == [
        {"day": "2026-04-10", "change": "first_seen", "device": "Oura Ring"}
    ]
    assert result["limitations"][0]["code"] == "partial_year"
    future = await tools.year_in_health(fake.client(), 2031, clock=CLOCK)
    assert future["limitations"][0]["code"] == "year_not_started"


async def test_overview_lists_what_the_record_holds_and_what_the_key_reads() -> None:
    fake = FakeObservatory()
    result = await tools.observatory_overview(fake.client(), clock=CLOCK)
    _assert_summary_only(result, fake)
    assert [m["metric"] for m in result["metrics"]] == ["sleep.stage", "vital.resting_heart_rate"]
    assert result["can_read"] == {"readings": True, "findings": True, "lab_results": True}
    narrow = await tools.observatory_overview(
        FakeObservatory(deny=("/api/v2/insights", "/api/v2/labs")).client(), clock=CLOCK
    )
    assert narrow["can_read"] == {"readings": True, "findings": False, "lab_results": False}
    assert narrow["limitations"][0]["code"] == "key_scope"
