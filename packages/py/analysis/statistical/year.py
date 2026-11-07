"""Year in Health: one calendar year of the record, read as coverage.

Pure engine (no DB, no HTTP, no LLM). The caller hands over, per analytical day,
which metrics and which device streams have at least one active observation,
plus each stream's all-time first and last observation. This module answers:

* which months hold data, and from which sources;
* which kinds of data (families) were recorded on which days;
* every run of days with no data, per family and overall — none is dropped;
* when a source first appeared or stopped (device changes);
* a few headline numbers, each computed for ONE source at a time with
  :func:`analysis.statistical.baselines.compute_baseline`. Nothing here is ever
  averaged across sources.

It returns structured facts and limitation codes. Wording belongs to the web
view; nothing here narrates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from contracts.analytical_time import AnalyticalTime, analytical_day

from .baselines import Sample, compute_baseline

# Kinds of data shown as rows in the year view. Ontology categories map onto
# them; ``computed`` metrics are derived from other rows and are not counted.
FAMILIES: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("heart", "Heart and vitals", frozenset({"vital", "cardio", "recovery"})),
    ("sleep", "Sleep", frozenset({"sleep"})),
    ("activity", "Activity and movement", frozenset({"activity", "mobility"})),
    ("body", "Body measurements", frozenset({"body"})),
    ("breathing", "Breathing", frozenset({"respiratory"})),
    ("nutrition", "Nutrition", frozenset({"nutrition"})),
    (
        "other",
        "Other records",
        frozenset({"symptom", "environment", "metabolic", "reproductive", "medication", "mental"}),
    ),
)
FAMILY_LABELS: dict[str, str] = {family_id: label for family_id, label, _ in FAMILIES}
FAMILY_ORDER: dict[str, int] = {family_id: i for i, (family_id, _, _) in enumerate(FAMILIES)}
DERIVED_CATEGORY = "computed"

# Scopes that describe one device's own readings. All-source day totals (the
# phone's "steps today" across every source) count toward coverage but are not
# a device, so they never create or extend a source.
DEVICE_SCOPES = frozenset({"interval_component", "device_day_total"})

# Coverage below this share of days is shown as low confidence.
LOW_COVERAGE = 0.5
# A source whose last reading is at least this many days before the end of the
# window is reported as stopped; a shorter silence is only a gap.
STOPPED_AFTER_DAYS = 14
# Headline numbers need this many days from one source; fewer is withheld,
# under HEADLINE_LOW_DAYS is shown as low confidence.
HEADLINE_MIN_DAYS = 7
HEADLINE_LOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class DayPresence:
    """At least one active observation of ``metric_id`` on ``day``."""

    metric_id: str
    category: str | None
    stream_id: str | None
    scope: str
    day: date
    count: int = 1


@dataclass(frozen=True, slots=True)
class StreamInfo:
    stream_id: str
    label: str
    plugin_id: str
    # All-time observation bounds (not ingest times), or None when unknown.
    first_at: datetime | None = None
    last_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GapRun:
    start: date
    end: date
    days: int
    # before_first: the record for this family had not started yet
    # inside: between two recorded days
    # after_last: nothing since the last recorded day up to the end of the window
    # no_data: nothing at all in the window
    kind: str


@dataclass(frozen=True, slots=True)
class FamilyYear:
    id: str
    label: str
    metric_ids: tuple[str, ...]
    days_with_data: int
    days_without_data: int
    first_day: date | None
    last_day: date | None
    mask: str
    gaps: tuple[GapRun, ...]
    longest_inside_gap: int
    confidence: str


@dataclass(frozen=True, slots=True)
class SourceYear:
    stream_id: str
    label: str
    plugin_id: str
    first_day: date
    last_day: date
    days_with_data: int
    months: tuple[int, ...]
    families: tuple[str, ...]
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    new_this_year: bool
    stopped_this_year: bool


@dataclass(frozen=True, slots=True)
class DeviceChange:
    day: date
    kind: str  # first_seen | last_seen
    stream_id: str
    label: str


@dataclass(frozen=True, slots=True)
class MonthYear:
    month: int
    days: int
    days_with_data: int
    coverage: float | None
    families: tuple[str, ...]
    source_ids: tuple[str, ...]
    first_seen_ids: tuple[str, ...]
    last_seen_ids: tuple[str, ...]
    # future: no elapsed day yet; none: no data; low: under half the days; ok
    confidence: str


@dataclass(frozen=True, slots=True)
class Headline:
    id: str
    label: str
    value: float
    unit: str | None
    stream_id: str | None = None
    source_label: str | None = None
    low: float | None = None
    high: float | None = None
    days: int | None = None
    of_days: int | None = None
    basis: str = "count"
    confidence: str = "ok"


@dataclass(frozen=True, slots=True)
class WithheldHeadline:
    id: str
    label: str
    stream_id: str | None
    source_label: str | None
    days: int
    reason: str


@dataclass(frozen=True, slots=True)
class Limitation:
    code: str
    day: date | None = None
    count: int | None = None


@dataclass(frozen=True, slots=True)
class YearSummary:
    year: int
    window_start: date
    window_end: date
    days_in_window: int
    days_with_data: int
    first_day: date | None
    last_day: date | None
    day_family_counts: tuple[int, ...]
    mask: str
    gaps: tuple[GapRun, ...]
    longest_inside_gap: int
    months: tuple[MonthYear, ...]
    families: tuple[FamilyYear, ...]
    sources: tuple[SourceYear, ...]
    device_changes: tuple[DeviceChange, ...]
    headlines: tuple[Headline, ...]
    withheld: tuple[WithheldHeadline, ...]
    limitations: tuple[Limitation, ...]
    confidence: str


@dataclass(frozen=True, slots=True)
class HeadlineMetric:
    """A metric whose per-source distribution is worth a headline."""

    id: str
    metric_id: str
    label: str
    unit: str | None
    # Keyed by stream id; ``None`` holds an all-source day total (the phone's
    # own total across every source), kept as its own series, never merged.
    samples_by_stream: Mapping[str | None, Sequence[Sample]] = field(default_factory=dict)
    all_sources_label: str | None = None


# ── Window ───────────────────────────────────────────────────────────────


def year_window(year: int, today: date) -> tuple[date, date] | None:
    """First and last analytical day of ``year`` that have already begun.

    ``None`` when the year has not started. A past year runs Jan 1 – Dec 31;
    the current year stops at ``today``.
    """
    start = date(year, 1, 1)
    if today < start:
        return None
    return start, min(date(year, 12, 31), today)


def family_for(category: str | None) -> str | None:
    """Family id for an ontology category; None for derived metrics."""
    if category == DERIVED_CATEGORY:
        return None
    for family_id, _, categories in FAMILIES:
        if category in categories:
            return family_id
    return "other"


def day_of(instant: datetime | None, config: AnalyticalTime) -> date | None:
    if instant is None:
        return None
    return analytical_day(instant, config)


# ── Runs ─────────────────────────────────────────────────────────────────


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def mask_for(days: Iterable[date], start: date, end: date) -> str:
    present = set(days)
    return "".join("1" if day in present else "0" for day in _days(start, end))


def gap_runs(mask: str, start: date) -> tuple[GapRun, ...]:
    """Every run of '0' in ``mask``, each tagged with where it sits.

    The runs partition the no-data days exactly: every '0' belongs to one run
    and no run holds a '1'. Nothing is filtered by length.
    """
    if "1" not in mask:
        if not mask:
            return ()
        return (GapRun(start, start + timedelta(days=len(mask) - 1), len(mask), "no_data"),)
    first = mask.index("1")
    last = mask.rindex("1")
    runs: list[GapRun] = []
    i = 0
    while i < len(mask):
        if mask[i] == "1":
            i += 1
            continue
        j = i
        while j + 1 < len(mask) and mask[j + 1] == "0":
            j += 1
        kind = "before_first" if j < first else "after_last" if i > last else "inside"
        runs.append(GapRun(start + timedelta(days=i), start + timedelta(days=j), j - i + 1, kind))
        i = j + 1
    return tuple(runs)


def _longest_inside(runs: Sequence[GapRun]) -> int:
    return max((run.days for run in runs if run.kind == "inside"), default=0)


def _coverage_confidence(days_with_data: int, days: int) -> str:
    if days == 0:
        return "future"
    if days_with_data == 0:
        return "none"
    return "low" if days_with_data / days < LOW_COVERAGE else "ok"


# ── Headlines ────────────────────────────────────────────────────────────


def _headlines_for(
    metric: HeadlineMetric,
    labels: Mapping[str, str],
) -> tuple[list[Headline], list[WithheldHeadline]]:
    """One headline per source, never pooled across sources."""
    shown: list[Headline] = []
    withheld: list[WithheldHeadline] = []

    def label_of(stream_id: str | None) -> str | None:
        if stream_id is None:
            return metric.all_sources_label
        return labels.get(stream_id, stream_id)

    for stream_id in sorted(
        metric.samples_by_stream, key=lambda s: (s is not None, (label_of(s) or "").lower())
    ):
        samples = list(metric.samples_by_stream[stream_id])
        baseline = compute_baseline(samples)
        if baseline is None:
            continue
        label = label_of(stream_id)
        if baseline.days < HEADLINE_MIN_DAYS:
            withheld.append(
                WithheldHeadline(
                    id=metric.id,
                    label=metric.label,
                    stream_id=stream_id,
                    source_label=label,
                    days=baseline.days,
                    reason="too_few_days",
                )
            )
            continue
        shown.append(
            Headline(
                id=metric.id,
                label=metric.label,
                value=round(baseline.p50, 1),
                unit=metric.unit,
                stream_id=stream_id,
                source_label=label,
                low=round(baseline.p10, 1),
                high=round(baseline.p90, 1),
                days=baseline.days,
                basis="median_one_source",
                confidence="low" if baseline.days < HEADLINE_LOW_DAYS else "ok",
            )
        )
    return shown, withheld


# ── Summary ──────────────────────────────────────────────────────────────


def summarize_year(
    *,
    year: int,
    window: tuple[date, date],
    presence: Iterable[DayPresence],
    streams: Mapping[str, StreamInfo],
    config: AnalyticalTime,
    headline_metrics: Sequence[HeadlineMetric] = (),
) -> YearSummary:
    window_start, window_end = window
    days_in_window = (window_end - window_start).days + 1

    family_days: dict[str, set[date]] = defaultdict(set)
    family_metrics: dict[str, set[str]] = defaultdict(set)
    stream_days: dict[str, set[date]] = defaultdict(set)
    stream_families: dict[str, set[str]] = defaultdict(set)
    any_days: set[date] = set()
    unattributed: set[date] = set()
    derived_seen = False

    for row in presence:
        if not window_start <= row.day <= window_end:
            continue
        family = family_for(row.category)
        if family is None:
            derived_seen = True
            continue
        family_days[family].add(row.day)
        family_metrics[family].add(row.metric_id)
        any_days.add(row.day)
        if row.scope not in DEVICE_SCOPES:
            continue
        if row.stream_id is None:
            unattributed.add(row.day)
            continue
        stream_days[row.stream_id].add(row.day)
        stream_families[row.stream_id].add(family)

    mask = mask_for(any_days, window_start, window_end)
    gaps = gap_runs(mask, window_start)
    all_days = _days(window_start, window_end)

    # Families: only those recorded at least once this year.
    families: list[FamilyYear] = []
    for family_id in sorted(family_days, key=lambda f: FAMILY_ORDER.get(f, 99)):
        days = family_days[family_id]
        fmask = mask_for(days, window_start, window_end)
        fgaps = gap_runs(fmask, window_start)
        families.append(
            FamilyYear(
                id=family_id,
                label=FAMILY_LABELS.get(family_id, family_id),
                metric_ids=tuple(sorted(family_metrics[family_id])),
                days_with_data=len(days),
                days_without_data=days_in_window - len(days),
                first_day=min(days),
                last_day=max(days),
                mask=fmask,
                gaps=fgaps,
                longest_inside_gap=_longest_inside(fgaps),
                confidence=_coverage_confidence(len(days), days_in_window),
            )
        )

    day_family_counts = tuple(
        sum(1 for family in families if family.mask[i] == "1") for i in range(days_in_window)
    )

    # Sources: device streams with readings this year.
    labels = {stream_id: info.label for stream_id, info in streams.items()}
    sources: list[SourceYear] = []
    changes: list[DeviceChange] = []
    for stream_id, days in stream_days.items():
        info = streams.get(stream_id) or StreamInfo(stream_id, "Unknown device", "unknown")
        first_ever = day_of(info.first_at, config)
        last_ever = day_of(info.last_at, config)
        new_this_year = first_ever is not None and window_start <= first_ever <= window_end
        stopped = (
            last_ever is not None
            and window_start <= last_ever <= window_end
            and (window_end - last_ever).days >= STOPPED_AFTER_DAYS
        )
        sources.append(
            SourceYear(
                stream_id=stream_id,
                label=info.label,
                plugin_id=info.plugin_id,
                first_day=min(days),
                last_day=max(days),
                days_with_data=len(days),
                months=tuple(sorted({day.month for day in days})),
                families=tuple(
                    sorted(stream_families[stream_id], key=lambda f: FAMILY_ORDER.get(f, 99))
                ),
                first_seen_at=info.first_at,
                last_seen_at=info.last_at,
                new_this_year=new_this_year,
                stopped_this_year=stopped,
            )
        )
        if new_this_year and first_ever is not None:
            changes.append(DeviceChange(first_ever, "first_seen", stream_id, info.label))
        if stopped and last_ever is not None:
            changes.append(DeviceChange(last_ever, "last_seen", stream_id, info.label))
    sources.sort(key=lambda s: (s.first_day, s.label.lower()))
    changes.sort(key=lambda c: (c.day, c.kind, c.label.lower()))

    months: list[MonthYear] = []
    for month in range(1, 13):
        month_days = [d for d in all_days if d.month == month]
        with_data = [d for d in month_days if d in any_days]
        months.append(
            MonthYear(
                month=month,
                days=len(month_days),
                days_with_data=len(with_data),
                coverage=round(len(with_data) / len(month_days), 4) if month_days else None,
                families=tuple(
                    family.id
                    for family in families
                    if any(d.month == month for d in family_days[family.id])
                ),
                source_ids=tuple(s.stream_id for s in sources if month in s.months),
                first_seen_ids=tuple(
                    c.stream_id for c in changes if c.kind == "first_seen" and c.day.month == month
                ),
                last_seen_ids=tuple(
                    c.stream_id for c in changes if c.kind == "last_seen" and c.day.month == month
                ),
                confidence=_coverage_confidence(len(with_data), len(month_days)),
            )
        )

    headlines: list[Headline] = [
        Headline(
            id="days_recorded",
            label="Days with any data",
            value=len(any_days),
            unit="days",
            days=len(any_days),
            of_days=days_in_window,
            confidence=_coverage_confidence(len(any_days), days_in_window),
        ),
        Headline(id="sources", label="Sources", value=len(sources), unit="sources"),
    ]
    longest = _longest_inside(gaps)
    if any_days:
        headlines.append(
            Headline(
                id="longest_gap",
                label="Longest stretch with nothing recorded",
                value=longest,
                unit="days",
            )
        )
    withheld: list[WithheldHeadline] = []
    for metric in headline_metrics:
        shown, held = _headlines_for(metric, labels)
        headlines.extend(shown)
        withheld.extend(held)

    limitations: list[Limitation] = [Limitation("time_basis"), Limitation("day_presence_only")]
    if window_end < date(year, 12, 31):
        limitations.append(Limitation("partial_year", day=window_end))
    if not any_days:
        limitations.append(Limitation("no_data"))
    elif min(any_days) > window_start:
        limitations.append(Limitation("record_starts_late", day=min(any_days)))
    if changes:
        limitations.append(Limitation("device_labels"))
    if unattributed:
        limitations.append(Limitation("unattributed", count=len(unattributed)))
    if derived_seen:
        limitations.append(Limitation("derived_excluded"))
    if withheld or any(h.confidence == "low" for h in headlines if h.stream_id):
        limitations.append(Limitation("headline_thin"))

    return YearSummary(
        year=year,
        window_start=window_start,
        window_end=window_end,
        days_in_window=days_in_window,
        days_with_data=len(any_days),
        first_day=min(any_days) if any_days else None,
        last_day=max(any_days) if any_days else None,
        day_family_counts=day_family_counts,
        mask=mask,
        gaps=gaps,
        longest_inside_gap=longest,
        months=tuple(months),
        families=tuple(families),
        sources=tuple(sources),
        device_changes=tuple(changes),
        headlines=tuple(headlines),
        withheld=tuple(withheld),
        limitations=tuple(limitations),
        confidence=_coverage_confidence(len(any_days), days_in_window),
    )
