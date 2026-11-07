"""Pure summaries of Observatory read-API payloads (no network, no clock).

Everything an MCP tool hands to an AI client is computed here, the same way
the Observatory web computes it: nights from ``sleep.stage`` intervals, one
value per day for daily totals, and a person's usual range from their own
history. Raw readings never leave this module; only per-day, per-night and
per-month summaries do.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The read API returns at most this many points per metric and keeps the
#: newest (``storage.timescale.observations``). A response this long was cut.
SERVER_POINT_CAP = 5000

#: The aggregation scope a daily-total metric is read from. Totals of other
#: scopes (one device, one provider) are never added to it or to each other.
ALL_SOURCE_DAY_TOTAL = "owner_all_source_day_total"
DAY_TOTAL_SCOPES = frozenset(
    {
        "device_day_total",
        "provider_account_day_total",
        "provider_reconciled_day_total",
        ALL_SOURCE_DAY_TOTAL,
    }
)

#: Same values as the web's sleep view (apps/web/app/lib/sleep.ts).
SESSION_GAP = timedelta(hours=4)
MAX_SEGMENT = timedelta(hours=24)
MIN_NIGHT_MINUTES = 60.0
DETAILED_ASLEEP_STAGES = ("core", "deep", "rem", "light")
CONTEXT_STAGES = ("in_bed", "unknown")


# ─── time ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TimeBasis:
    """How readings are grouped into days.

    ``source`` is ``settings`` when the person's analytical-time setting was
    read, ``utc`` when it could not be (the key may not read it).
    """

    tz: tzinfo
    zone: str
    day_start_minutes: int
    source: str

    def describe(self) -> str:
        start = f"{self.day_start_minutes // 60:02d}:{self.day_start_minutes % 60:02d}"
        return f"{self.zone}, days start {start}"


UTC_BASIS = TimeBasis(tz=timezone.utc, zone="UTC", day_start_minutes=0, source="utc")


def time_basis(settings: dict[str, Any] | None) -> TimeBasis:
    """The basis from ``GET /api/v2/settings/analytical-time``, else UTC."""

    if not isinstance(settings, dict):
        return UTC_BASIS
    zone = settings.get("time_zone")
    minutes = settings.get("day_boundary_minutes")
    if not isinstance(zone, str) or not zone:
        return UTC_BASIS
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC_BASIS
    if not isinstance(minutes, int) or not 0 <= minutes < 24 * 60:
        minutes = 0
    return TimeBasis(tz=tz, zone=zone, day_start_minutes=minutes, source="settings")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def analytical_day(t: datetime, basis: TimeBasis) -> date:
    """The person's day for an instant reading (day starts at the boundary)."""

    return (t.astimezone(basis.tz) - timedelta(minutes=basis.day_start_minutes)).date()


def total_day(point: dict[str, Any], t: datetime, basis: TimeBasis) -> date:
    """The day a daily total belongs to.

    Totals are stamped at the phone's local midnight. With the capture offset
    that is exact; without it, half a day of slack keeps the total on its own
    day for any offset within twelve hours (the year view's rule).
    """

    offset = point.get("tz_offset_minutes")
    if isinstance(offset, int) and -16 * 60 <= offset <= 16 * 60:
        return (t + timedelta(minutes=offset)).date()
    return (t.astimezone(basis.tz) + timedelta(hours=12)).date()


def clock(t: datetime, basis: TimeBasis) -> str:
    return t.astimezone(basis.tz).strftime("%H:%M")


# ─── small statistics ──────────────────────────────────────────────────


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated quantile (numpy's default), ``None`` when empty."""

    ordered = sorted(v for v in values if isinstance(v, int | float) and math.isfinite(v))
    if not ordered:
        return None
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def median(values: Sequence[float]) -> float | None:
    return quantile(values, 0.5)


def mean(values: Sequence[float]) -> float | None:
    finite = [v for v in values if isinstance(v, int | float) and math.isfinite(v)]
    return sum(finite) / len(finite) if finite else None


def rnd(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    rounded = round(value, digits)
    return int(rounded) if digits == 0 else rounded


def usual_range(values: Sequence[float], digits: int = 1) -> dict[str, Any] | None:
    """Median and the 10th-90th percentile band of a person's own history."""

    if not values:
        return None
    return {
        "median": rnd(median(values), digits),
        "low": rnd(quantile(values, 0.1), digits),
        "high": rnd(quantile(values, 0.9), digits),
        "days": len(values),
    }


def place(value: float | None, band: dict[str, Any] | None) -> str | None:
    """``below`` / ``within`` / ``above`` the usual band (no judgement)."""

    if value is None or not band or band.get("low") is None or band.get("high") is None:
        return None
    if value < band["low"]:
        return "below"
    if value > band["high"]:
        return "above"
    return "within"


def minutes_of_day(t: datetime, basis: TimeBasis, *, around_noon: bool) -> float:
    """Clock minutes, measured from noon for bedtimes so midnight is not a seam."""

    local = t.astimezone(basis.tz)
    minutes = local.hour * 60 + local.minute + local.second / 60
    if around_noon:
        return (minutes - 12 * 60) % (24 * 60)
    return minutes


def clock_label(minutes: float | None, *, around_noon: bool) -> str | None:
    if minutes is None:
        return None
    total = round(minutes + (12 * 60 if around_noon else 0)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def runs_of_missing(days: Iterable[date], present: set[date]) -> list[dict[str, Any]]:
    """Every run of days without data, in order (none dropped for being short)."""

    runs: list[dict[str, Any]] = []
    start: date | None = None
    previous: date | None = None
    for day in days:
        if day in present:
            if start is not None and previous is not None:
                runs.append(_run(start, previous))
            start = None
        elif start is None:
            start = day
        previous = day
    if start is not None and previous is not None:
        runs.append(_run(start, previous))
    return runs


def _run(start: date, end: date) -> dict[str, Any]:
    return {"from": start.isoformat(), "to": end.isoformat(), "days": (end - start).days + 1}


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ─── sleep ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Night:
    """One night, the way the web's Sleep page derives it."""

    night_of: date
    bedtime: datetime
    wake: datetime
    asleep_min: float
    tracked_min: float
    in_bed_min: float
    stage_min: dict[str, float]
    sources: int

    def as_dict(self, basis: TimeBasis) -> dict[str, Any]:
        stages = {
            stage: rnd(minutes, 0)
            for stage, minutes in sorted(self.stage_min.items())
            if minutes >= 0.5
        }
        efficiency = (
            rnd(100 * self.asleep_min / self.in_bed_min, 0) if self.in_bed_min > 0 else None
        )
        return {
            "night_of": self.night_of.isoformat(),
            "bedtime": clock(self.bedtime, basis),
            "wake": clock(self.wake, basis),
            "asleep_h": rnd(self.asleep_min / 60, 2),
            "in_bed_h": rnd(self.in_bed_min / 60, 2),
            "efficiency_pct": efficiency,
            "stage_minutes": stages,
            "sources": self.sources,
        }


@dataclass(frozen=True, slots=True)
class _Segment:
    start: datetime
    end: datetime
    stage: str
    stream: str


def _stage(code: str) -> str:
    normalized = "_".join(code.strip().lower().replace("-", " ").split())
    return "asleep" if normalized == "asleep_unspecified" else normalized


def _segment(point: dict[str, Any]) -> _Segment | None:
    code = point.get("code")
    start = parse_time(point.get("t"))
    end = parse_time(point.get("interval_end"))
    if not isinstance(code, str) or start is None or end is None:
        return None
    if end <= start or end - start > MAX_SEGMENT:
        return None
    stream = point.get("stream_id") or point.get("source_id") or "unknown-source"
    return _Segment(start=start, end=end, stage=_stage(code), stream=str(stream))


def _reconcile(segments: list[_Segment]) -> tuple[float, float, float, dict[str, float]]:
    """Sweep the union of intervals (port of ``reconcileTimeline`` in sleep.ts).

    Asleep minutes count only where no source says awake; a slice where two
    detailed stages overlap is ``conflict`` but still asleep clock time.
    """

    events: dict[datetime, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seg in segments:
        events[seg.start][seg.stage] += 1
        events[seg.end][seg.stage] -= 1
    boundaries = sorted(events)
    active: dict[str, int] = {}
    stage_min: dict[str, float] = defaultdict(float)
    asleep = tracked = in_bed = 0.0
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        for stage, delta in events[start].items():
            count = active.get(stage, 0) + delta
            if count > 0:
                active[stage] = count
            else:
                active.pop(stage, None)
        slice_min = (boundaries[index + 1] - start).total_seconds() / 60
        if slice_min <= 0:
            continue
        detailed = [stage for stage in DETAILED_ASLEEP_STAGES if stage in active]
        has_asleep = bool(detailed) or "asleep" in active
        has_awake = "awake" in active
        has_in_bed = "in_bed" in active
        if has_asleep:
            tracked += slice_min
            if has_awake or len(detailed) > 1:
                shown = "conflict"
            elif len(detailed) == 1:
                shown = detailed[0]
            else:
                shown = "asleep"
            if not has_awake:
                asleep += slice_min
            stage_min[shown] += slice_min
        elif has_awake:
            tracked += slice_min
            stage_min["awake"] += slice_min
        if has_in_bed or has_asleep or has_awake:
            in_bed += slice_min
        for stage in CONTEXT_STAGES:
            if stage in active:
                stage_min[stage] += slice_min
    return asleep, tracked, in_bed, dict(stage_min)


def sleep_nights(points: Iterable[dict[str, Any]], basis: TimeBasis) -> list[Night]:
    """Nights from ``sleep.stage`` points, oldest first.

    Sessions split on a gap of four hours or more; a session is shown on the
    evening it began (before local noon counts as the previous evening), and
    one with under an hour asleep is not a night. Same rules as the web, except
    the noon split uses the person's time zone when known (the web uses UTC).
    """

    segments = sorted(
        (seg for seg in (_segment(p) for p in points) if seg is not None),
        key=lambda seg: (seg.start, seg.end),
    )
    sessions: list[list[_Segment]] = []
    session_end: datetime | None = None
    for seg in segments:
        if session_end is None or seg.start - session_end >= SESSION_GAP:
            sessions.append([seg])
            session_end = seg.end
        else:
            sessions[-1].append(seg)
            session_end = max(session_end, seg.end)

    nights: list[Night] = []
    for session in sessions:
        asleep, tracked, in_bed, stage_min = _reconcile(session)
        if asleep < MIN_NIGHT_MINUTES:
            continue
        bedtime = session[0].start
        wake = max(seg.end for seg in session)
        local_start = bedtime.astimezone(basis.tz)
        night_of = local_start.date()
        if local_start.hour < 12:
            night_of -= timedelta(days=1)
        nights.append(
            Night(
                night_of=night_of,
                bedtime=bedtime,
                wake=wake,
                asleep_min=asleep,
                tracked_min=tracked,
                in_bed_min=in_bed,
                stage_min=stage_min,
                sources=len({seg.stream for seg in session}),
            )
        )
    return nights


def sleep_summary(nights: Sequence[Night], basis: TimeBasis) -> dict[str, Any]:
    if not nights:
        return {"nights": 0}
    asleep_h = [n.asleep_min / 60 for n in nights]
    asleep_total = sum(n.asleep_min for n in nights)
    shares: dict[str, float] = defaultdict(float)
    for night in nights:
        for stage in ("deep", "rem", "core", "light", "asleep", "conflict"):
            shares[stage] += night.stage_min.get(stage, 0.0)
    shortest = min(nights, key=lambda n: n.asleep_min)
    longest = max(nights, key=lambda n: n.asleep_min)
    in_bed = [n.in_bed_min for n in nights if n.in_bed_min > 0]
    return {
        "nights": len(nights),
        "asleep_h": {
            "mean": rnd(mean(asleep_h), 2),
            "median": rnd(median(asleep_h), 2),
            "low": rnd(quantile(asleep_h, 0.1), 2),
            "high": rnd(quantile(asleep_h, 0.9), 2),
        },
        "typical_bedtime": clock_label(
            median([minutes_of_day(n.bedtime, basis, around_noon=True) for n in nights]),
            around_noon=True,
        ),
        "typical_wake": clock_label(
            median([minutes_of_day(n.wake, basis, around_noon=False) for n in nights]),
            around_noon=False,
        ),
        "shortest": {
            "night_of": shortest.night_of.isoformat(),
            "asleep_h": rnd(shortest.asleep_min / 60, 2),
        },
        "longest": {
            "night_of": longest.night_of.isoformat(),
            "asleep_h": rnd(longest.asleep_min / 60, 2),
        },
        "stage_share_pct": {
            stage: rnd(100 * minutes / asleep_total, 0)
            for stage, minutes in shares.items()
            if asleep_total > 0 and minutes > 0
        },
        "efficiency_pct": rnd(
            100 * sum(n.asleep_min for n in nights if n.in_bed_min > 0) / sum(in_bed), 0
        )
        if in_bed
        else None,
    }


def sleep_months(nights: Sequence[Night], basis: TimeBasis) -> list[dict[str, Any]]:
    by_month: dict[str, list[Night]] = defaultdict(list)
    for night in nights:
        by_month[night.night_of.strftime("%Y-%m")].append(night)
    rows = []
    for month in sorted(by_month):
        group = by_month[month]
        rows.append(
            {
                "month": month,
                "nights": len(group),
                "asleep_h_mean": rnd(mean([n.asleep_min / 60 for n in group]), 2),
                "typical_bedtime": clock_label(
                    median([minutes_of_day(n.bedtime, basis, around_noon=True) for n in group]),
                    around_noon=True,
                ),
                "typical_wake": clock_label(
                    median([minutes_of_day(n.wake, basis, around_noon=False) for n in group]),
                    around_noon=False,
                ),
            }
        )
    return rows


# ─── daily values ──────────────────────────────────────────────────────


@dataclass(slots=True)
class DailyValues:
    """One value per day for one metric, and how it was read."""

    values: dict[date, float] = field(default_factory=dict)
    counts: dict[date, int] = field(default_factory=dict)
    lows: dict[date, float] = field(default_factory=dict)
    highs: dict[date, float] = field(default_factory=dict)
    basis: str = "none"
    streams: int = 0
    other_streams: int = 0
    #: Days with readings but no all-source total (left out, never mixed in).
    uncovered_days: int = 0


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def daily_totals(points: Iterable[dict[str, Any]], basis: TimeBasis) -> DailyValues:
    """One total per day for a daily-total metric.

    Reads the all-source day total (the phone's own sum across sources) when
    it exists; days that only have other rows are left out and counted in
    ``uncovered_days``. Without any all-source total, the totals of ONE stream
    are used, the stream with the most days, and the others are counted, never
    added: two devices counting the same steps must not double them. Within
    that stream a day total wins over its own components; the two are never
    added either.
    """

    rows = [p for p in points if _finite(p.get("value")) is not None]
    all_source = [p for p in rows if p.get("aggregation_scope") == ALL_SOURCE_DAY_TOTAL]
    out = DailyValues()
    if all_source:
        other_days: set[date] = set()
        for point in rows:
            t = parse_time(point.get("t"))
            if t is None:
                continue
            if point.get("aggregation_scope") != ALL_SOURCE_DAY_TOTAL:
                other_days.add(total_day(point, t, basis))
                continue
            day = total_day(point, t, basis)
            value = _finite(point.get("value"))
            if value is None:
                continue
            out.values[day] = max(out.values.get(day, value), value)
            out.counts[day] = 1
        out.basis = "all_source_day_total"
        out.streams = 1
        out.uncovered_days = len(other_days - set(out.values))
        return out

    totals: dict[str, dict[date, float]] = defaultdict(dict)
    parts: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for point in rows:
        t = parse_time(point.get("t"))
        if t is None:
            continue
        stream = str(point.get("stream_id") or point.get("source_id") or "unknown")
        value = _finite(point.get("value")) or 0.0
        if point.get("aggregation_scope") in DAY_TOTAL_SCOPES:
            day = total_day(point, t, basis)
            totals[stream][day] = max(totals[stream].get(day, value), value)
        else:
            parts[stream][analytical_day(t, basis)] += value
    by_stream: dict[str, dict[date, float]] = {}
    for stream in set(totals) | set(parts):
        merged = dict(parts.get(stream, {}))
        merged.update(totals.get(stream, {}))  # a day total replaces its components
        by_stream[stream] = merged
    if not by_stream:
        return out
    chosen = max(by_stream, key=lambda s: (len(by_stream[s]), sum(by_stream[s].values()), s))
    out.values = dict(by_stream[chosen])
    out.counts = {day: 1 for day in out.values}
    out.basis = "one_stream_total"
    out.streams = len(by_stream)
    out.other_streams = len(by_stream) - 1
    return out


def daily_readings(points: Iterable[dict[str, Any]], basis: TimeBasis) -> DailyValues:
    """Median, low and high per day for a reading metric (heart rate, HRV...).

    Day-total rows are left out: they are a different scale.
    """

    per_day: dict[date, list[float]] = defaultdict(list)
    streams: set[str] = set()
    for point in points:
        if point.get("aggregation_scope") in DAY_TOTAL_SCOPES:
            continue
        value = _finite(point.get("value"))
        t = parse_time(point.get("t"))
        if value is None or t is None:
            continue
        per_day[analytical_day(t, basis)].append(value)
        streams.add(str(point.get("stream_id") or point.get("source_id") or "unknown"))
    out = DailyValues(basis="daily_median_of_readings", streams=len(streams))
    for day, values in per_day.items():
        out.values[day] = median(values)  # type: ignore[assignment]
        out.counts[day] = len(values)
        out.lows[day] = min(values)
        out.highs[day] = max(values)
    return out


def truncated(points: Sequence[dict[str, Any]]) -> datetime | None:
    """The earliest returned time when the server cut the window, else None."""

    if len(points) < SERVER_POINT_CAP:
        return None
    times = [t for t in (parse_time(p.get("t")) for p in points) if t is not None]
    return min(times) if times else None
