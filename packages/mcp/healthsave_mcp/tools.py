"""The read tools. Each one makes a few GETs and returns a summary.

Every result carries the window it covers, the units of every number, where
it came from (``read_from``), and ``limitations``: stable codes with a plain
sentence, the way the Observatory web words its limits. No tool writes, and
no tool returns raw readings: only per-day, per-night and per-month summaries,
findings the statistical engine already computed, and lab results.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import derive
from .client import ObservatoryClient, ObservatoryError
from .derive import TimeBasis

Clock = Callable[[], datetime]

SLEEP_PERIODS: dict[str, tuple[str, int | None]] = {
    "last_night": ("7d", 1),
    "last_7_nights": ("7d", 7),
    "last_30_nights": ("30d", 30),
    "last_90_nights": ("90d", 90),
    "last_365_nights": ("1y", 365),
    "this_year": ("1y", None),
}
#: Day periods read a wider range than they show. The server's range starts
#: at "now minus N days", which falls after the first day's midnight total, so
#: an exact range would silently drop the oldest day.
DAY_PERIODS: dict[str, tuple[str, int | None]] = {
    "today": ("30d", 1),
    "last_7_days": ("30d", 7),
    "last_30_days": ("90d", 30),
    "last_90_days": ("1y", 90),
    "last_365_days": ("all", 365),
    "this_year": ("all", None),
}
#: Detail rows are listed for at most this many days or nights; longer
#: windows are summarized per month instead.
DETAIL_LIMIT = 14
MONTHLY_AFTER = 45
DAILY_ROWS_LIMIT = 92

ACTIVITY = (
    # metric id, key, unit shown, divisor from the canonical unit, digits
    ("activity.steps", "steps", "steps", 1.0, 0),
    ("activity.active_energy", "active_energy", "kcal", 1.0, 0),
    ("activity.exercise_minutes", "exercise", "min", 1.0, 0),
    ("activity.distance_walking_running", "walking_running_distance", "km", 1000.0, 2),
)
TODAY_READINGS = (
    ("vital.resting_heart_rate", "Resting heart rate", "bpm", 0),
    ("vital.hrv_sdnn", "Heart rate variability (SDNN)", "ms", 0),
    ("vital.respiratory_rate", "Respiratory rate", "breaths/min", 1),
    ("vital.blood_oxygen", "Blood oxygen", "%", 1),
    ("body.wrist_temperature", "Wrist temperature", "degC", 2),
    ("body.weight", "Body weight", "kg", 1),
)
UNIT_LABELS = {"count/min": "bpm", "count": "count"}

NOT_ADVICE = (
    "Descriptive readings from the person's own record, compared with their own history. "
    "Not a diagnosis and not medical advice."
)


def _lim(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _now(clock: Clock | None) -> datetime:
    return (clock or (lambda: datetime.now(UTC)))()


class Reader:
    """One tool call's view of the Observatory: client plus per-call caches."""

    def __init__(self, client: ObservatoryClient, clock: Clock | None = None) -> None:
        self.client = client
        self.now = _now(clock)
        self.read_from: list[str] = []
        self.limitations: list[dict[str, str]] = []
        self._basis: TimeBasis | None = None
        self._labels: dict[str, str] | None = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items() if v is not None)
        self.read_from.append(f"GET {path}" + (f"?{query}" if query else ""))
        return await self.client.get(path, params)

    def note(self, code: str, detail: str) -> None:
        if not any(item["code"] == code and item["detail"] == detail for item in self.limitations):
            self.limitations.append(_lim(code, detail))

    async def basis(self) -> TimeBasis:
        if self._basis is None:
            try:
                settings = await self.get("/api/v2/settings/analytical-time")
            except ObservatoryError as exc:
                if exc.code not in ("key_scope", "not_found"):
                    raise
                settings = None
            self._basis = derive.time_basis(settings)
            if self._basis.source != "settings":
                self.note(
                    "time_basis_utc",
                    "Days are grouped in UTC: this key cannot read the person's time zone "
                    "setting, so a day may start or end a few hours off local midnight.",
                )
        return self._basis

    async def labels(self) -> dict[str, str]:
        """Stream id -> device label (``Apple Watch``), for naming sources."""

        if self._labels is None:
            try:
                body = await self.get("/api/v2/streams")
            except ObservatoryError:
                body = {}
            self._labels = {
                str(s.get("id")): str(s.get("device_label") or s.get("origin_key") or "unknown")
                for s in (body.get("streams") or [])
                if isinstance(s, dict)
            }
        return self._labels

    def today(self, basis: TimeBasis) -> date:
        return derive.analytical_day(self.now, basis)

    def result(self, tool: str, **payload: Any) -> dict[str, Any]:
        return {
            "tool": tool,
            **payload,
            "limitations": self.limitations,
            "read_from": self.read_from,
            "note": NOT_ADVICE,
        }


def _window(today: date, days: int | None) -> tuple[date, date]:
    if days is None:
        return date(today.year, 1, 1), today
    return today - timedelta(days=days), today


def _check_period(
    period: str, allowed: dict[str, tuple[str, int | None]]
) -> tuple[str, int | None]:
    if period not in allowed:
        raise ValueError(f"period must be one of {', '.join(allowed)}; got {period!r}")
    return allowed[period]


def _cut(
    reader: Reader,
    points: Sequence[dict[str, Any]],
    what: str,
    basis: TimeBasis,
    window_start: date,
) -> date | None:
    """The first whole day kept when the server cut the window, else None."""

    earliest = derive.truncated(points)
    if earliest is None:
        return None
    day = derive.analytical_day(earliest, basis) + timedelta(days=1)
    if day <= window_start:
        return None
    reader.note(
        "window_cut",
        f"The Observatory returns at most {derive.SERVER_POINT_CAP:,} readings per request and "
        f"keeps the newest, so {what} before {day.isoformat()} is not in this answer. "
        "Ask for a shorter period for full detail.",
    )
    return day


# ─── overview ──────────────────────────────────────────────────────────


async def observatory_overview(
    client: ObservatoryClient, *, clock: Clock | None = None
) -> dict[str, Any]:
    reader = Reader(client, clock)
    readiness = await reader.get("/api/v2/readiness")
    metrics = sorted(
        (
            {
                "metric": m.get("metric_id"),
                "name": m.get("display_name"),
                "days_with_data": m.get("days_with_data"),
                "first": (m.get("first_observation_at") or "")[:10] or None,
                "last": (m.get("last_observation_at") or "")[:10] or None,
            }
            for m in readiness.get("metrics") or []
            if isinstance(m, dict) and (m.get("days_with_data") or m.get("observation_count"))
        ),
        key=lambda m: (-(m["days_with_data"] or 0), str(m["metric"])),
    )
    try:
        devices_body = await reader.get("/api/v2/devices")
    except ObservatoryError as exc:
        devices_body = {}
        reader.note(exc.code, str(exc))
    devices = [
        {
            "device": d.get("device_label"),
            "first_seen": (d.get("first_seen_at") or "")[:10] or None,
            "last_seen": (d.get("last_seen_at") or "")[:10] or None,
        }
        for d in devices_body.get("devices") or []
        if isinstance(d, dict)
    ]
    last_sync: dict[str, Any] | None
    try:
        run = await reader.get("/api/v2/sync/runs/latest")
        last_sync = {
            "completed_at": run.get("completed_at") or run.get("started_at"),
            "status": run.get("status"),
            "records_received": run.get("records_received"),
        }
    except ObservatoryError as exc:
        if exc.code not in ("not_found", "key_scope"):
            raise
        last_sync = None
    can_read = {"readings": True}
    for name, path in (("findings", "/api/v2/insights/findings"), ("lab_results", "/api/v2/labs")):
        try:
            await reader.get(path, {"limit": 1} if name == "findings" else None)
            can_read[name] = True
        except ObservatoryError as exc:
            if exc.code != "key_scope":
                raise
            can_read[name] = False
    if not can_read.get("findings"):
        reader.note(
            "key_scope",
            "This key reads its own readings (sleep, activity, heart, year), not findings or "
            "lab results. On the server, `healthsave mcp key` makes a read key that can.",
        )
    if len(metrics) > 40:
        reader.note(
            "list_cut",
            f"{len(metrics)} kinds of data have readings; the 40 with the most days are listed.",
        )
    return reader.result(
        "observatory_overview",
        last_reading_at=readiness.get("last_observation_at"),
        last_received_at=readiness.get("last_ingested_at"),
        last_sync=last_sync,
        kinds_of_data=len(metrics),
        metrics=metrics[:40],
        devices=devices,
        can_read=can_read,
    )


# ─── sleep ─────────────────────────────────────────────────────────────


async def sleep_summary(
    client: ObservatoryClient, period: str = "last_30_nights", *, clock: Clock | None = None
) -> dict[str, Any]:
    range_, days = _check_period(period, SLEEP_PERIODS)
    reader = Reader(client, clock)
    basis = await reader.basis()
    body = await reader.get("/api/v2/metrics/sleep.stage/series", {"range": range_})
    points = body.get("points") or []
    today = reader.today(basis)
    start, end = _window(today, days)
    cut = _cut(reader, points, "sleep", basis, start)
    nights = [n for n in derive.sleep_nights(points, basis) if start <= n.night_of <= end]
    if period == "last_night":
        nights = nights[-1:] if nights and nights[-1].night_of >= today - timedelta(days=2) else []

    window: dict[str, Any] = {
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "time_basis": basis.describe(),
        "night_of": "the evening a night began (a night that started after midnight counts "
        "for the evening before)",
    }
    if not nights:
        reader.note("no_data", f"No night with at least an hour asleep between {start} and {end}.")
        return reader.result("sleep_summary", window=window, summary={"nights": 0})

    first_night = nights[0].night_of
    if period != "last_night":
        evenings = derive.date_range(
            max(start, cut or start, first_night), today - timedelta(days=1)
        )
        missing = derive.runs_of_missing(evenings, {n.night_of for n in nights})
        window["evenings_counted"] = len(evenings)
        if first_night > start and cut is None:
            reader.note(
                "record_starts_late",
                f"The first night in this period is {first_night.isoformat()}; there is no sleep "
                "data before it.",
            )
    else:
        missing = []

    payload: dict[str, Any] = {
        "window": window,
        "summary": derive.sleep_summary(nights, basis),
        "units": {
            "asleep_h": "hours asleep (awake minutes inside the night excluded)",
            "in_bed_h": "hours from first to last sleep reading",
            "stage_minutes": "minutes",
            "stage_share_pct": "% of time asleep",
            "efficiency_pct": "% of time in bed spent asleep",
            "bedtime": "local clock time",
        },
    }
    if missing:
        payload["nights_without_data"] = {
            "count": sum(run["days"] for run in missing),
            "runs": missing[-10:],
        }
        if len(missing) > 10:
            reader.note(
                "list_cut", f"{len(missing)} runs of nights without data; the last 10 are listed."
            )
    if len(nights) > MONTHLY_AFTER:
        payload["months"] = derive.sleep_months(nights, basis)
    payload["nights"] = [n.as_dict(basis) for n in nights[-DETAIL_LIMIT:]]
    if len(nights) > DETAIL_LIMIT:
        payload["nights_listed"] = f"the last {DETAIL_LIMIT} of {len(nights)}"
    if any(n.stage_min.get("conflict") for n in nights):
        reader.note(
            "sources_disagree",
            "On some nights two sources reported different stages at the same time; that time "
            "is shown as `conflict` and still counts as asleep unless a source said awake.",
        )
    return reader.result("sleep_summary", **payload)


# ─── activity ──────────────────────────────────────────────────────────


async def activity_summary(
    client: ObservatoryClient, period: str = "last_30_days", *, clock: Clock | None = None
) -> dict[str, Any]:
    range_, days = _check_period(period, DAY_PERIODS)
    reader = Reader(client, clock)
    basis = await reader.basis()
    ids = ",".join(metric for metric, *_ in ACTIVITY)
    body = await reader.get("/api/v2/series", {"ids": ids, "range": range_})
    by_id = {
        (item.get("metric") or {}).get("id"): item
        for item in body.get("series") or []
        if isinstance(item, dict) and "metric" in item
    }
    today = reader.today(basis)
    start, end = _window(today, days)
    window = {
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "time_basis": basis.describe(),
    }

    per_metric: dict[str, dict[date, float]] = {}
    totals: dict[str, Any] = {}
    units: dict[str, str] = {}
    for metric_id, key, unit, divisor, digits in ACTIVITY:
        points = (by_id.get(metric_id) or {}).get("points") or []
        _cut(reader, points, metric_id, basis, start)
        daily = derive.daily_totals(points, basis)
        values = {d: v / divisor for d, v in daily.values.items()}
        per_metric[key] = values
        units[key] = f"{unit} per day"
        if daily.basis == "one_stream_total" and daily.other_streams:
            reader.note(
                "one_source_of_several",
                f"{metric_id}: no all-source day total; the totals of one source are used and "
                f"{daily.other_streams} other source(s) are left out, not added (they may count "
                "the same activity).",
            )
        full_days = [
            values[d] for d in derive.date_range(start, today - timedelta(days=1)) if d in values
        ]
        before = [
            values[d]
            for d in derive.date_range(today - timedelta(days=28), today - timedelta(days=1))
            if d in values
        ]
        if not values:
            totals[key] = {"days_with_data": 0}
            continue
        best_day = max(
            (d for d in values if start <= d < today), key=lambda d: values[d], default=None
        )
        entry: dict[str, Any] = {
            "days_with_data": len(full_days),
            "per_day": {
                "mean": derive.rnd(derive.mean(full_days), digits),
                "median": derive.rnd(derive.median(full_days), digits),
                "low": derive.rnd(derive.quantile(full_days, 0.1), digits),
                "high": derive.rnd(derive.quantile(full_days, 0.9), digits),
            }
            if full_days
            else None,
            "total": derive.rnd(sum(full_days), digits) if full_days else None,
            "best_day": {
                "date": best_day.isoformat(),
                "value": derive.rnd(values[best_day], digits),
            }
            if best_day
            else None,
        }
        if today in values:
            entry["today_so_far"] = derive.rnd(values[today], digits)
            entry["usual_full_day"] = derive.usual_range(before, digits)
        totals[key] = entry
    if any(today in values for values in per_metric.values()):
        reader.note(
            "today_in_progress",
            "Today's totals are still counting and are not in the per-day numbers.",
        )

    listed = [d for d in derive.date_range(start, end) if any(d in v for v in per_metric.values())]
    payload: dict[str, Any] = {"window": window, "totals": totals, "units": units}
    if (end - start).days > MONTHLY_AFTER:
        months: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for key, values in per_metric.items():
            for d, v in values.items():
                if start <= d < today:
                    months[d.strftime("%Y-%m")][key].append(v)
        payload["months"] = [
            {
                "month": month,
                **{
                    f"{key}_per_day": derive.rnd(
                        derive.mean(vals), 0 if key != "walking_running_distance" else 2
                    )
                    for key, vals in months[month].items()
                },
                "days_with_data": max(len(vals) for vals in months[month].values()),
            }
            for month in sorted(months)
        ]
    payload["days"] = [
        {
            "date": d.isoformat(),
            **{
                key: derive.rnd(values[d], 2 if key == "walking_running_distance" else 0)
                for key, values in per_metric.items()
                if d in values
            },
        }
        for d in listed[-DETAIL_LIMIT:]
    ]
    if not listed:
        reader.note("no_data", f"No activity totals between {start} and {end}.")
    return reader.result("activity_summary", **payload)


# ─── today ─────────────────────────────────────────────────────────────


def _main_stream(per_stream: dict[str, derive.DailyValues], since: date) -> str | None:
    if not per_stream:
        return None
    return max(
        per_stream,
        key=lambda s: (
            sum(1 for d in per_stream[s].values if d >= since),
            max(per_stream[s].values, default=date.min),
            s,  # a tie is broken the same way every time
        ),
    )


def _readings_by_stream(
    points: Sequence[dict[str, Any]], basis: TimeBasis
) -> dict[str, derive.DailyValues]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        groups[str(point.get("stream_id") or point.get("source_id") or "unknown")].append(point)
    out = {}
    for stream, rows in groups.items():
        daily = derive.daily_readings(rows, basis)
        if daily.values:
            out[stream] = daily
    return out


async def today_vs_usual(
    client: ObservatoryClient, *, clock: Clock | None = None
) -> dict[str, Any]:
    reader = Reader(client, clock)
    basis = await reader.basis()
    ids = (
        [metric for metric, *_ in TODAY_READINGS] + [m for m, *_ in ACTIVITY[:3]] + ["sleep.stage"]
    )
    body = await reader.get("/api/v2/series", {"ids": ",".join(ids), "range": "30d"})
    by_id = {
        (item.get("metric") or {}).get("id"): item.get("points") or []
        for item in body.get("series") or []
        if isinstance(item, dict) and "metric" in item
    }
    today = reader.today(basis)
    labels = await reader.labels()
    readings = []
    for metric_id, name, unit, digits in TODAY_READINGS:
        per_stream = _readings_by_stream(by_id.get(metric_id) or [], basis)
        stream = _main_stream(per_stream, today - timedelta(days=28))
        if stream is None:
            continue
        values = per_stream[stream].values
        latest_day = max(values)
        if latest_day < today - timedelta(days=2):
            continue
        history = [values[d] for d in values if latest_day - timedelta(days=28) <= d < latest_day]
        band = derive.usual_range(history, digits)
        value = derive.rnd(values[latest_day], digits)
        entry = {
            "metric": metric_id,
            "name": name,
            "unit": unit,
            "day": latest_day.isoformat(),
            "value": value,
            "source": labels.get(stream, "one source"),
            "usual": band,
            "place": derive.place(value, band) if band and band["days"] >= 7 else None,
        }
        if band is None or band["days"] < 7:
            entry["usual_note"] = "fewer than 7 earlier days from this source; no usual range yet"
        others = [labels.get(s, "another source") for s in per_stream if s != stream]
        if others:
            entry["other_sources_not_mixed_in"] = others
        readings.append(entry)

    totals = []
    for metric_id, _key, unit, divisor, digits in ACTIVITY[:3]:
        daily = derive.daily_totals(by_id.get(metric_id) or [], basis)
        values = {d: v / divisor for d, v in daily.values.items()}
        before = [
            values[d]
            for d in derive.date_range(today - timedelta(days=28), today - timedelta(days=1))
            if d in values
        ]
        if not values:
            continue
        totals.append(
            {
                "metric": metric_id,
                "unit": unit,
                "today_so_far": derive.rnd(values.get(today), digits) if today in values else None,
                "yesterday": derive.rnd(values.get(today - timedelta(days=1)), digits)
                if today - timedelta(days=1) in values
                else None,
                "usual_full_day": derive.usual_range(before, digits),
            }
        )
    if totals:
        reader.note(
            "today_in_progress",
            "Today's totals are still counting; compare them with a full day only at day's end.",
        )

    nights = derive.sleep_nights(by_id.get("sleep.stage") or [], basis)
    last_night: dict[str, Any] | None = None
    if nights and nights[-1].night_of >= today - timedelta(days=2):
        latest = nights[-1]
        earlier = [
            n.asleep_min / 60
            for n in nights[:-1]
            if n.night_of >= latest.night_of - timedelta(days=28)
        ]
        band = derive.usual_range(earlier, 2)
        last_night = {
            **latest.as_dict(basis),
            "usual_asleep_h": band,
            "place": derive.place(round(latest.asleep_min / 60, 2), band)
            if band and band["days"] >= 7
            else None,
        }

    recovery = None
    try:
        found = await reader.get(
            "/api/v2/insights/findings", {"type": "recovery_score", "limit": 1}
        )
        rows = found.get("findings") or []
        if rows:
            data = rows[0].get("structured_data") or {}
            recovery = {
                "score": data.get("score"),
                "scale": "0-100, from the Observatory's statistical engine",
                "computed_at": rows[0].get("created_at"),
                "inputs_vs_baseline": data.get("contributors"),
                "missing_inputs": data.get("missing_inputs"),
            }
    except ObservatoryError as exc:
        if exc.code != "key_scope":
            raise
        reader.note("key_scope", "This key cannot read findings, so no recovery score is shown.")

    if not readings and not totals and last_night is None:
        reader.note("no_data", "Nothing recorded in the last two days.")
    return reader.result(
        "today_vs_usual",
        today=today.isoformat(),
        time_basis=basis.describe(),
        usual_means="median and 10th-90th percentile of the same source over the previous 28 days",
        readings=readings,
        totals=totals,
        last_night=last_night,
        recovery=recovery,
    )


# ─── one metric over time ──────────────────────────────────────────────


async def metric_trend(
    client: ObservatoryClient,
    metric_id: str,
    period: str = "last_90_days",
    *,
    clock: Clock | None = None,
) -> dict[str, Any]:
    range_, days = _check_period(period, DAY_PERIODS)
    reader = Reader(client, clock)
    catalog = await reader.get("/api/v2/metrics")
    known = {m.get("id"): m for m in catalog if isinstance(m, dict)}
    if metric_id not in known:
        close = difflib.get_close_matches(
            metric_id, [k for k in known if isinstance(k, str)], n=5, cutoff=0.4
        )
        raise ValueError(
            f"unknown metric {metric_id!r}"
            + (f"; did you mean {', '.join(close)}?" if close else "")
            + " observatory_overview lists the metrics this record holds."
        )
    meta = known[metric_id]
    if meta.get("value_type") != "quantity":
        raise ValueError(f"{metric_id} has no numeric values; use sleep_summary for sleep stages.")
    basis = await reader.basis()
    body = await reader.get(f"/api/v2/metrics/{metric_id}/series", {"range": range_})
    points = body.get("points") or []
    today = reader.today(basis)
    start, end = _window(today, days)
    cut = _cut(reader, points, metric_id, basis, start)
    unit = UNIT_LABELS.get(str(meta.get("canonical_unit")), meta.get("canonical_unit"))
    is_total = any(p.get("aggregation_scope") in derive.DAY_TOTAL_SCOPES for p in points)
    window = {
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "time_basis": basis.describe(),
    }
    labels = await reader.labels()

    rows: list[dict[str, Any]] = []
    if is_total:
        daily = derive.daily_totals(points, basis)
        values = {d: v for d, v in daily.values.items() if start <= d <= end}
        how = "one total per day" + (
            " (all sources, as the phone sums them)"
            if daily.basis == "all_source_day_total"
            else " (one source)"
        )
        source = "all sources" if daily.basis == "all_source_day_total" else "one source"
        if daily.other_streams:
            reader.note(
                "one_source_of_several",
                f"{daily.other_streams} other source(s) left out, not added.",
            )
        rows = [{"date": d.isoformat(), "total": derive.rnd(values[d], 2)} for d in sorted(values)]
        others: list[str] = []
        if today in values:
            reader.note("today_in_progress", "Today's total is still counting.")
    else:
        per_stream = _readings_by_stream(points, basis)
        stream = _main_stream(per_stream, start)
        if stream is None:
            values = {}
            source = None
            others = []
        else:
            chosen = per_stream[stream]
            values = {d: v for d, v in chosen.values.items() if start <= d <= end}
            rows = [
                {
                    "date": d.isoformat(),
                    "median": derive.rnd(values[d], 2),
                    "low": derive.rnd(chosen.lows[d], 2),
                    "high": derive.rnd(chosen.highs[d], 2),
                    "readings": chosen.counts[d],
                }
                for d in sorted(values)
            ]
            source = labels.get(stream, "one source")
            others = [labels.get(s, "another source") for s in per_stream if s != stream]
        how = "median, lowest and highest reading per day, from one source"
    if not values:
        reader.note("no_data", f"No {metric_id} readings between {start} and {end}.")
        return reader.result(
            "metric_trend",
            metric=metric_id,
            name=meta.get("display_name"),
            unit=unit,
            window=window,
        )
    payload: dict[str, Any] = {
        "metric": metric_id,
        "name": meta.get("display_name"),
        "unit": unit,
        "window": window,
        "per_day": how,
        "source": source,
        "days_with_data": len(values),
        "usual": derive.usual_range(list(values.values()), 2),
    }
    if others:
        payload["other_sources_not_mixed_in"] = others
    if cut is None and min(values) > start and days is not None:
        reader.note(
            "record_starts_late",
            f"The first day with data in this period is {min(values).isoformat()}.",
        )
    if len(rows) > DAILY_ROWS_LIMIT or (end - start).days > DAILY_ROWS_LIMIT:
        by_month: dict[str, list[float]] = defaultdict(list)
        for d, v in values.items():
            by_month[d.strftime("%Y-%m")].append(v)
        payload["months"] = [
            {
                "month": month,
                "days": len(vals),
                "median": derive.rnd(derive.median(vals), 2),
                "low": derive.rnd(derive.quantile(vals, 0.1), 2),
                "high": derive.rnd(derive.quantile(vals, 0.9), 2),
            }
            for month, vals in sorted(by_month.items())
        ]
        payload["days"] = rows[-DETAIL_LIMIT:]
    else:
        payload["days"] = rows
    return reader.result("metric_trend", **payload)


# ─── findings ──────────────────────────────────────────────────────────


def _compact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {k: _compact(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        items = [_compact(v, depth + 1) for v in value[:12]]
        if len(value) > 12:
            items.append(f"... {len(value) - 12} more")
        return items
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "..."
    return value


async def findings(
    client: ObservatoryClient,
    kind: str | None = None,
    limit: int = 10,
    *,
    clock: Clock | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 25))
    reader = Reader(client, clock)
    try:
        body = await reader.get("/api/v2/insights/findings", {"type": kind, "limit": limit})
    except ObservatoryError as exc:
        if exc.code != "key_scope":
            raise
        reader.note(exc.code, str(exc))
        return reader.result("findings", findings=[], count=0)
    rows = [
        {
            "id": f.get("id"),
            "type": f.get("finding_type"),
            "metric": f.get("metric"),
            "severity": f.get("severity"),
            "computed_at": f.get("created_at"),
            "data": _compact(f.get("structured_data") or {}),
        }
        for f in body.get("findings") or []
        if isinstance(f, dict)
    ]
    correlations = None
    if kind is None:
        try:
            corr = await reader.get("/api/v2/insights/correlations", {"limit": 10})
            correlations = _compact(corr.get("correlations") if isinstance(corr, dict) else corr)
        except ObservatoryError as exc:
            if exc.code not in ("key_scope", "not_found"):
                raise
    if not rows:
        reader.note(
            "no_findings",
            "The statistical engine has no findings yet. It needs some weeks of data, and it runs "
            "on a schedule in the worker.",
        )
    return reader.result(
        "findings",
        about="Findings are computed by the Observatory's deterministic statistical engine "
        "(baselines, anomalies, trends, correlations, recovery). Each one stands on the data "
        "in `data`; none is a diagnosis.",
        count=len(rows),
        findings=rows,
        correlations=correlations,
    )


# ─── labs ──────────────────────────────────────────────────────────────


def _result_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": (r.get("specimen_at") or "")[:10] or None,
        "value": r.get("value"),
        "comparator": r.get("comparator"),
        "unit": r.get("display_unit") or r.get("unit"),
        "lab": r.get("lab"),
        "lab_range": [r.get("reference_low"), r.get("reference_high")],
        "band": r.get("band"),
    }


async def lab_results(
    client: ObservatoryClient, loinc: str | None = None, *, clock: Clock | None = None
) -> dict[str, Any]:
    reader = Reader(client, clock)
    about = (
        "Each result is placed against the reference range its own lab printed (below / within / "
        "above). Results from different labs are never averaged."
    )
    try:
        if loinc:
            marker = await reader.get(f"/api/v2/labs/{loinc.strip()}")
        else:
            body = await reader.get("/api/v2/labs")
    except ObservatoryError as exc:
        if exc.code == "key_scope":
            reader.note(exc.code, str(exc))
            return reader.result("lab_results", about=about, markers=[])
        if exc.code == "not_found" and loinc:
            reader.note("no_data", f"No results for LOINC {loinc}.")
            return reader.result("lab_results", about=about, markers=[])
        raise
    if loinc:
        results = marker.get("results") or []
        payload: dict[str, Any] = {
            "marker": {
                "loinc": marker.get("loinc"),
                "name": marker.get("name"),
                "unit": marker.get("display_unit") or marker.get("unit"),
                "result_count": marker.get("result_count"),
                "labs": marker.get("lab_count"),
                "results": [_result_row(r) for r in results[-20:] if isinstance(r, dict)],
                "assessment": _compact(marker.get("assessment")),
                "same_marker_two_labs_within_14_days": _compact(marker.get("gaps") or []),
                "wearable_cross_match": _compact(marker.get("cross_match")),
            }
        }
        if len(results) > 20:
            reader.note("list_cut", f"{len(results)} results; the newest 20 are listed.")
        return reader.result("lab_results", about=about, **payload)
    markers = []
    for m in body.get("markers") or []:
        if not isinstance(m, dict):
            continue
        results = m.get("results") or []
        markers.append(
            {
                "loinc": m.get("loinc"),
                "name": m.get("name"),
                "unit": m.get("display_unit") or m.get("unit"),
                "result_count": m.get("result_count"),
                "latest": _result_row(results[0]) if results else None,
                "assessment": _compact(m.get("assessment")),
                "two_labs_within_14_days": m.get("gap_count"),
            }
        )
    if not markers:
        reader.note(
            "no_data", "No blood test results are imported (`healthsave labs import FILE.csv`)."
        )
    return reader.result("lab_results", about=about, count=len(markers), markers=markers)


# ─── year in health ────────────────────────────────────────────────────


async def year_in_health(
    client: ObservatoryClient, year: int | None = None, *, clock: Clock | None = None
) -> dict[str, Any]:
    reader = Reader(client, clock)
    year = int(year) if year else reader.now.year
    try:
        body = await reader.get(f"/api/v2/year/{year}")
    except ObservatoryError as exc:
        if exc.code == "rejected":
            reader.note("year_not_started", str(exc))
            return reader.result("year_in_health", year=year)
        raise
    labels = {
        s.get("stream_id"): s.get("label") for s in body.get("sources") or [] if isinstance(s, dict)
    }
    months = [
        {
            "month": m.get("month"),
            "days": m.get("days"),
            "days_with_data": m.get("days_with_data"),
            "coverage": m.get("coverage"),
            "kinds_of_data": m.get("families"),
            "sources": [labels.get(i, "unlabelled") for i in m.get("source_ids") or []],
            "first_seen": [labels.get(i, "unlabelled") for i in m.get("first_seen_ids") or []],
            "confidence": m.get("confidence"),
        }
        for m in body.get("months") or []
        if isinstance(m, dict)
    ]
    families = [
        {
            k: f.get(k)
            for k in (
                "id",
                "label",
                "days_with_data",
                "days_without_data",
                "first_day",
                "last_day",
                "longest_inside_gap",
                "confidence",
            )
        }
        | {"gaps_inside": [g for g in f.get("gaps") or [] if g.get("kind") == "inside"][:10]}
        for f in body.get("families") or []
        if isinstance(f, dict)
    ]
    sources = [
        {
            k: s.get(k)
            for k in (
                "label",
                "first_day",
                "last_day",
                "days_with_data",
                "families",
                "new_this_year",
                "stopped_this_year",
            )
        }
        for s in body.get("sources") or []
        if isinstance(s, dict)
    ]
    for item in body.get("limitations") or []:
        if isinstance(item, dict) and item.get("code"):
            detail = ", ".join(f"{k}={v}" for k, v in item.items() if k != "code" and v is not None)
            reader.note(str(item["code"]), detail or "reported by the Observatory's year view")
    return reader.result(
        "year_in_health",
        year=body.get("year"),
        window={
            "from": body.get("window_start"),
            "to": body.get("window_end"),
            "time_zone": body.get("time_zone"),
            "day_start": body.get("day_boundary"),
        },
        days_in_window=body.get("days_in_window"),
        days_with_data=body.get("days_with_data"),
        longest_gap_days=body.get("longest_inside_gap"),
        gaps=[g for g in body.get("gaps") or [] if isinstance(g, dict)][:20],
        months=months,
        kinds_of_data=families,
        sources=sources,
        device_changes=[
            {"day": c.get("day"), "change": c.get("kind"), "device": c.get("label")}
            for c in body.get("device_changes") or []
            if isinstance(c, dict)
        ],
        headlines=_compact(body.get("headlines") or []),
        withheld=_compact(body.get("withheld") or []),
        confidence=body.get("confidence"),
        units={
            "coverage": "share of days with any data (0-1)",
            "headlines": "each headline names its unit and its one source",
        },
    )
