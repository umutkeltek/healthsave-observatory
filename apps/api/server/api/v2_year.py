"""v2 Year in Health read API: one calendar year of the record, read as coverage.

``GET /api/v2/year/{year}`` returns, for one owner and one year: months covered,
sources per month, device changes (each source's first and last observation),
every run of days with no data per kind of data, and a few headline numbers.

Rules this surface keeps (ADR-0001, the two-brain rule):

* Headline numbers are computed per source by the pure engine
  (``analysis.statistical.year`` → ``baselines.compute_baseline``); nothing is
  averaged across sources.
* No gap is dropped: the gap runs partition every day without data.
* Limitations come back as codes with their facts; the web view words them.
  Nothing here narrates.

Days are the person's analytical days (``/api/v2/analytical-time``: time zone
plus day boundary). The SQL lives in ``storage.timescale.year`` (and the
headline series in ``storage.timescale.observations``). The aggregate walks a
year of the canonical store, so it rides the process-level SWR cache like the
readiness aggregates. The cache key carries the owner's last ingest time, so
a sync is visible on the next read (no stale year after new data), and the
superseded key is dropped so the cache does not grow with every sync. A change
that does not move the last ingest time (a deletion of older rows) shows once
the TTL runs out.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from analysis.statistical import year as engine
from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, V2Model
from contracts.analytical_time import (
    DEFAULT_DAY_BOUNDARY_MINUTES,
    DEFAULT_TIME_ZONE,
    AnalyticalTime,
    analytical_day,
    analytical_day_bounds,
)
from contracts.ontology import get_metric
from fastapi import APIRouter, Depends, HTTPException, Path
from storage.defaults import readiness_repository
from storage.timescale.observations import default_repository as observation_repository
from storage.timescale.observatory_settings import default_repository as settings_repository
from storage.timescale.year import default_repository as year_repository

from ..db.session import async_session
from .access import ReadOwner
from .deps import get_session, verify_api_key
from .swr import DEFAULT_TTL_SECONDS, owner_cache_key, v2_read_cache

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])

# New data changes the cache key (see ``_ingest_stamp``); the TTL only has to
# follow the calendar (today's analytical day moving on).
YEAR_CACHE_TTL_SECONDS = max(DEFAULT_TTL_SECONDS, 600.0) if DEFAULT_TTL_SECONDS > 0 else 0.0
# One year of daily values per source stays far under this.
HEADLINE_SERIES_LIMIT = 20_000
ALL_SOURCES_DAY_TOTAL = "owner_all_source_day_total"

# (headline id, metric id, label, unit, label for an all-source day total)
HEADLINE_METRICS: tuple[tuple[str, str, str, str, str], ...] = (
    ("resting_heart_rate", "vital.resting_heart_rate", "Resting heart rate", "bpm", ""),
    ("steps", "activity.steps", "Daily steps", "steps", "All sources, daily total"),
)

Confidence = Literal["ok", "low", "none", "future"]


class YearGapView(V2Model):
    start: date
    end: date
    days: int
    kind: Literal["before_first", "inside", "after_last", "no_data"]


class YearFamilyView(V2Model):
    id: str
    label: str
    metric_ids: list[str]
    days_with_data: int
    days_without_data: int
    first_day: date | None
    last_day: date | None
    # One character per day of the window: "1" data, "0" none.
    mask: str
    gaps: list[YearGapView]
    longest_inside_gap: int
    confidence: Confidence


class YearSourceView(V2Model):
    stream_id: UUID
    label: str
    source_plugin_id: str
    first_day: date
    last_day: date
    days_with_data: int
    months: list[int]
    families: list[str]
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    new_this_year: bool
    stopped_this_year: bool


class YearDeviceChangeView(V2Model):
    day: date
    kind: Literal["first_seen", "last_seen"]
    stream_id: UUID
    label: str


class YearMonthView(V2Model):
    month: int
    days: int
    days_with_data: int
    coverage: float | None
    families: list[str]
    source_ids: list[UUID]
    first_seen_ids: list[UUID]
    last_seen_ids: list[UUID]
    confidence: Confidence


class YearHeadlineView(V2Model):
    id: str
    label: str
    value: float
    unit: str | None
    stream_id: UUID | None
    source_label: str | None
    low: float | None
    high: float | None
    days: int | None
    of_days: int | None
    basis: str
    confidence: Confidence


class YearWithheldView(V2Model):
    id: str
    label: str
    stream_id: UUID | None
    source_label: str | None
    days: int
    reason: str


class YearLimitationView(V2Model):
    code: str
    day: date | None
    count: int | None


class YearInHealth(V2Model):
    year: int
    owner_id: UUID
    time_zone: str
    day_boundary: str
    generated_at: datetime
    window_start: date
    window_end: date
    days_in_window: int
    days_with_data: int
    first_day: date | None
    last_day: date | None
    # Kinds of data recorded on each day of the window, in order.
    day_family_counts: list[int]
    mask: str
    gaps: list[YearGapView]
    longest_inside_gap: int
    months: list[YearMonthView]
    families: list[YearFamilyView]
    sources: list[YearSourceView]
    device_changes: list[YearDeviceChangeView]
    headlines: list[YearHeadlineView]
    withheld: list[YearWithheldView]
    limitations: list[YearLimitationView]
    confidence: Confidence


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _gap(run: engine.GapRun) -> YearGapView:
    return YearGapView(start=run.start, end=run.end, days=run.days, kind=run.kind)  # type: ignore[arg-type]


def _view(summary: engine.YearSummary, *, owner_id: UUID, config: AnalyticalTime) -> YearInHealth:
    return YearInHealth(
        year=summary.year,
        owner_id=owner_id,
        time_zone=config.time_zone,
        day_boundary=config.boundary_label,
        generated_at=datetime.now(UTC),
        window_start=summary.window_start,
        window_end=summary.window_end,
        days_in_window=summary.days_in_window,
        days_with_data=summary.days_with_data,
        first_day=summary.first_day,
        last_day=summary.last_day,
        day_family_counts=list(summary.day_family_counts),
        mask=summary.mask,
        gaps=[_gap(run) for run in summary.gaps],
        longest_inside_gap=summary.longest_inside_gap,
        months=[
            YearMonthView(
                month=m.month,
                days=m.days,
                days_with_data=m.days_with_data,
                coverage=m.coverage,
                families=list(m.families),
                source_ids=[UUID(s) for s in m.source_ids],
                first_seen_ids=[UUID(s) for s in m.first_seen_ids],
                last_seen_ids=[UUID(s) for s in m.last_seen_ids],
                confidence=m.confidence,  # type: ignore[arg-type]
            )
            for m in summary.months
        ],
        families=[
            YearFamilyView(
                id=f.id,
                label=f.label,
                metric_ids=list(f.metric_ids),
                days_with_data=f.days_with_data,
                days_without_data=f.days_without_data,
                first_day=f.first_day,
                last_day=f.last_day,
                mask=f.mask,
                gaps=[_gap(run) for run in f.gaps],
                longest_inside_gap=f.longest_inside_gap,
                confidence=f.confidence,  # type: ignore[arg-type]
            )
            for f in summary.families
        ],
        sources=[
            YearSourceView(
                stream_id=UUID(s.stream_id),
                label=s.label,
                source_plugin_id=s.plugin_id,
                first_day=s.first_day,
                last_day=s.last_day,
                days_with_data=s.days_with_data,
                months=list(s.months),
                families=list(s.families),
                first_seen_at=s.first_seen_at,
                last_seen_at=s.last_seen_at,
                new_this_year=s.new_this_year,
                stopped_this_year=s.stopped_this_year,
            )
            for s in summary.sources
        ],
        device_changes=[
            YearDeviceChangeView(
                day=c.day,
                kind=c.kind,  # type: ignore[arg-type]
                stream_id=UUID(c.stream_id),
                label=c.label,
            )
            for c in summary.device_changes
        ],
        headlines=[
            YearHeadlineView(
                id=h.id,
                label=h.label,
                value=h.value,
                unit=h.unit,
                stream_id=_uuid(h.stream_id),
                source_label=h.source_label,
                low=h.low,
                high=h.high,
                days=h.days,
                of_days=h.of_days,
                basis=h.basis,
                confidence=h.confidence,  # type: ignore[arg-type]
            )
            for h in summary.headlines
        ],
        withheld=[
            YearWithheldView(
                id=w.id,
                label=w.label,
                stream_id=_uuid(w.stream_id),
                source_label=w.source_label,
                days=w.days,
                reason=w.reason,
            )
            for w in summary.withheld
        ],
        limitations=[
            YearLimitationView(code=item.code, day=item.day, count=item.count)
            for item in summary.limitations
        ],
        confidence=summary.confidence,  # type: ignore[arg-type]
    )


async def _analytical_time(session, owner_id: UUID) -> AnalyticalTime:
    """The owner's own setting, else the primary person's, else UTC / 04:00."""
    for candidate in dict.fromkeys((owner_id, DEFAULT_OWNER_ID)):
        settings = await settings_repository.get(session, owner_id=candidate)
        if settings is not None:
            return AnalyticalTime(settings.time_zone, settings.day_boundary_minutes)
    return AnalyticalTime(DEFAULT_TIME_ZONE, DEFAULT_DAY_BOUNDARY_MINUTES)


async def build_year(
    session, *, owner_id: UUID, year: int, now: datetime | None = None
) -> YearInHealth:
    """Fetch the year's rows for one owner and let the engine read them."""
    config = await _analytical_time(session, owner_id)
    today = analytical_day(now or datetime.now(UTC), config)
    window = engine.year_window(year, today)
    if window is None:
        raise HTTPException(
            status_code=422,
            detail=f"year {year} has not started yet (today is {today.isoformat()})",
        )
    start, _ = analytical_day_bounds(window[0], config)
    _, end = analytical_day_bounds(window[1], config)

    presence_rows = await year_repository.day_presence(
        session,
        owner_id=owner_id,
        start=start,
        end=end,
        time_zone=config.time_zone,
        day_boundary_minutes=config.day_boundary_minutes,
    )
    presence = []
    for row in presence_rows:
        metric = get_metric(row.metric_id)
        presence.append(
            engine.DayPresence(
                metric_id=row.metric_id,
                category=metric.category if metric is not None else None,
                stream_id=str(row.stream_id) if row.stream_id else None,
                scope=row.aggregation_scope,
                day=row.day,
                count=row.observation_count,
            )
        )

    streams = {
        str(row.stream_id): engine.StreamInfo(
            stream_id=str(row.stream_id),
            label=(row.device_label or "").strip() or row.origin_key or "Unknown device",
            plugin_id=row.source_plugin_id,
            first_at=row.first_at,
            last_at=row.last_at,
        )
        for row in await year_repository.stream_bounds(session, owner_id=owner_id)
    }

    headline_metrics = []
    for headline_id, metric_id, label, unit, all_label in HEADLINE_METRICS:
        points = await observation_repository.query_series(
            session,
            owner_id=owner_id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            metric_id=metric_id,
            start=start,
            end=end,
            limit=HEADLINE_SERIES_LIMIT,
            rollup_scope_only=True,
        )
        by_stream: dict[str | None, list[tuple[datetime, float]]] = defaultdict(list)
        for point in points:
            if point.value is None:
                continue
            if point.aggregation_scope == ALL_SOURCES_DAY_TOTAL:
                # The phone's own all-source total: one series, not a device.
                key = None
            elif point.stream_id is None:
                continue
            else:
                key = str(point.stream_id)
            by_stream[key].append((point.t, float(point.value)))
        headline_metrics.append(
            engine.HeadlineMetric(
                id=headline_id,
                metric_id=metric_id,
                label=label,
                unit=unit,
                samples_by_stream=dict(by_stream),
                all_sources_label=all_label or None,
            )
        )

    summary = engine.summarize_year(
        year=year,
        window=window,
        presence=presence,
        streams=streams,
        config=config,
        headline_metrics=headline_metrics,
    )
    return _view(summary, owner_id=owner_id, config=config)


async def _load_year(owner_id: UUID, year: int) -> YearInHealth:
    """Session-owning loader, so an SWR background refresh can outlive a request."""
    async with async_session() as session:
        return await build_year(session, owner_id=owner_id, year=year)


_READINESS = readiness_repository()
# (owner, year) -> the cache key last used, so a newer ingest drops the old one.
_LAST_KEYS: dict[tuple[UUID, int], str] = {}


async def _ingest_stamp(session, owner_id: UUID) -> str:
    """The owner's last ingest time: one index-assisted scalar (migration 018)."""
    stamp = await _READINESS.fetch_last_ingested_at(session, owner_id=owner_id)
    return stamp.isoformat() if stamp else "none"


@router.get("/year/{year}", response_model=YearInHealth)
async def year_in_health(
    year: Annotated[int, Path(ge=1970, le=2200, description="Calendar year, like 2026")],
    session=Depends(get_session),
    owner_id: ReadOwner = DEFAULT_OWNER_ID,
) -> YearInHealth:
    """One year of the record: months, sources, device changes, every gap."""
    key = owner_cache_key(f"year:{year}:{await _ingest_stamp(session, owner_id)}", owner_id)
    previous = _LAST_KEYS.get((owner_id, year))
    if previous is not None and previous != key:
        v2_read_cache.drop(previous)
    _LAST_KEYS[(owner_id, year)] = key
    return await v2_read_cache.get(
        key,
        lambda: _load_year(owner_id, year),
        ttl_seconds=YEAR_CACHE_TTL_SECONDS,
    )
