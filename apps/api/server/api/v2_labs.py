"""v2 Labs read API — blood test results as a first-class source (Labs slice 1).

``GET /api/v2/labs`` lists every marker with its results and the labs (streams)
they came from; ``GET /api/v2/labs/{loinc}`` returns one marker's series.

Each result carries the reference range the lab printed for it. Results from
different labs stay separate rows tagged with their stream; nothing here
averages across labs. The SQL lives in ``storage.timescale.labs`` (and the
wearable series in ``storage.timescale.observations``); every reading — band
position, change against earlier results, gaps between labs, the cross-match
card — is computed by the pure ``analysis.statistical.labs`` engine. This module
only fetches and shapes (typed, additive v2).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from analysis.statistical import labs as engine
from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, V2Model
from contracts.findings import FindingCard
from fastapi import APIRouter, Depends, HTTPException
from normalization.labs import FLAG_DATE_ONLY, display_unit, is_valid_loinc, metric_id_for
from storage.timescale import registry
from storage.timescale.labs import LabResultRow
from storage.timescale.labs import default_repository as lab_repository
from storage.timescale.observations import default_repository as observation_repository

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2/labs", dependencies=[Depends(verify_api_key)])


class LabResultView(V2Model):
    id: UUID
    specimen_at: datetime
    date_only: bool
    value: float
    comparator: str | None
    unit: str
    display_unit: str
    reference_low: float | None
    reference_high: float | None
    lab: str
    stream_id: UUID
    source_plugin_id: str
    panel: str | None
    quality_flags: list[str]
    # Against this result's own lab range: below / within / above / no_range /
    # censored. band_fraction is 0 at the low bound, 1 at the high bound.
    band: str
    band_fraction: float | None


class LabAssessmentView(V2Model):
    latest_band: str
    previous_specimen_at: datetime | None
    previous_from_other_lab: bool
    change: float | None
    change_pct: float | None
    direction: str | None
    change_withheld: str | None
    prior_count: int
    prior_min: float | None
    prior_max: float | None
    versus_history: str | None
    outside_streak: int


class LabGapView(V2Model):
    earlier_id: UUID
    later_id: UUID
    earlier_lab: str
    later_lab: str
    earlier_specimen_at: datetime
    later_specimen_at: datetime
    earlier_value: float
    later_value: float
    unit: str
    days_apart: float
    difference: float | None
    difference_pct: float | None
    earlier_band: str
    later_band: str
    bands_disagree: bool


class LabCrossMatchView(V2Model):
    related_metric_id: str
    related_label: str
    related_unit: str
    stream_id: str | None
    stream_label: str | None
    card: FindingCard | None
    reason: str | None


class LabSourceView(V2Model):
    stream_id: UUID
    lab: str
    source_plugin_id: str
    result_count: int
    first_specimen_at: datetime
    last_specimen_at: datetime


class LabMarkerView(V2Model):
    loinc: str
    metric_id: str
    name: str
    unit: str
    display_unit: str
    result_count: int
    lab_count: int
    first_specimen_at: datetime
    last_specimen_at: datetime
    results: list[LabResultView]
    assessment: LabAssessmentView | None
    gap_count: int
    related_metric_id: str | None


class LabsOverview(V2Model):
    markers: list[LabMarkerView]
    labs: list[LabSourceView]
    count: int
    result_count: int


class LabMarkerDetail(LabMarkerView):
    gaps: list[LabGapView]
    cross_match: LabCrossMatchView | None


def _point(row: LabResultRow) -> engine.LabPoint:
    return engine.LabPoint(
        specimen_at=row.specimen_at,
        value=row.numeric_value,
        unit=row.canonical_unit,
        stream_id=str(row.stream_id),
        lab=row.lab_name,
        comparator=row.value_comparator,
        reference_low=row.reference_low,
        reference_high=row.reference_high,
    )


def _result_view(row: LabResultRow) -> LabResultView:
    band = engine.band_position(_point(row))
    return LabResultView(
        id=row.id,
        specimen_at=row.specimen_at,
        date_only=FLAG_DATE_ONLY in row.quality_flags,
        value=row.numeric_value,
        comparator=row.value_comparator,
        unit=row.canonical_unit,
        display_unit=display_unit(row.canonical_unit),
        reference_low=row.reference_low,
        reference_high=row.reference_high,
        lab=row.lab_name,
        stream_id=row.stream_id,
        source_plugin_id=row.source_plugin_id,
        panel=row.panel,
        quality_flags=list(row.quality_flags),
        band=band.status,
        band_fraction=None if band.fraction is None else round(band.fraction, 4),
    )


def _assessment_view(points: list[engine.LabPoint]) -> LabAssessmentView | None:
    assessed = engine.assess_marker(points)
    if assessed is None:
        return None
    return LabAssessmentView(
        latest_band=assessed.latest_band.status,
        previous_specimen_at=assessed.previous.specimen_at if assessed.previous else None,
        previous_from_other_lab=assessed.previous_from_other_lab,
        change=assessed.change,
        change_pct=None if assessed.change_pct is None else round(assessed.change_pct, 2),
        direction=assessed.direction,
        change_withheld=assessed.change_withheld,
        prior_count=assessed.prior_count,
        prior_min=assessed.prior_min,
        prior_max=assessed.prior_max,
        versus_history=assessed.versus_history,
        outside_streak=assessed.outside_streak,
    )


def _gap_views(rows: list[LabResultRow]) -> list[LabGapView]:
    by_key = {(str(r.stream_id), r.specimen_at): r for r in rows}
    views = []
    for gap in engine.lab_gaps([_point(r) for r in rows]):
        earlier = by_key[(gap.earlier.stream_id, gap.earlier.specimen_at)]
        later = by_key[(gap.later.stream_id, gap.later.specimen_at)]
        views.append(
            LabGapView(
                earlier_id=earlier.id,
                later_id=later.id,
                earlier_lab=earlier.lab_name,
                later_lab=later.lab_name,
                earlier_specimen_at=earlier.specimen_at,
                later_specimen_at=later.specimen_at,
                earlier_value=earlier.numeric_value,
                later_value=later.numeric_value,
                unit=later.canonical_unit,
                days_apart=gap.days_apart,
                difference=gap.difference,
                difference_pct=None if gap.difference_pct is None else round(gap.difference_pct, 2),
                earlier_band=gap.earlier_band.status,
                later_band=gap.later_band.status,
                bands_disagree=gap.bands_disagree,
            )
        )
    return views


def _marker_fields(loinc: str, rows: list[LabResultRow]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: (r.specimen_at, r.lab_name))
    latest = ordered[-1]
    return {
        "loinc": loinc,
        "metric_id": metric_id_for(loinc),
        "name": latest.marker_name or f"LOINC {loinc}",
        "unit": latest.canonical_unit,
        "display_unit": display_unit(latest.canonical_unit),
        "result_count": len(ordered),
        "lab_count": len({r.stream_id for r in ordered}),
        "first_specimen_at": ordered[0].specimen_at,
        "last_specimen_at": latest.specimen_at,
        "results": [_result_view(row) for row in ordered],
        "assessment": _assessment_view([_point(row) for row in ordered]),
        "gap_count": len(engine.lab_gaps([_point(row) for row in ordered])),
        "related_metric_id": (
            engine.PAIRINGS[loinc].metric_id if loinc in engine.PAIRINGS else None
        ),
    }


def _sources(rows: list[LabResultRow]) -> list[LabSourceView]:
    by_stream: dict[UUID, list[LabResultRow]] = defaultdict(list)
    for row in rows:
        by_stream[row.stream_id].append(row)
    views = [
        LabSourceView(
            stream_id=stream_id,
            lab=stream_rows[-1].lab_name,
            source_plugin_id=stream_rows[-1].source_plugin_id,
            result_count=len(stream_rows),
            first_specimen_at=min(r.specimen_at for r in stream_rows),
            last_specimen_at=max(r.specimen_at for r in stream_rows),
        )
        for stream_id, stream_rows in by_stream.items()
    ]
    return sorted(views, key=lambda view: view.lab.lower())


@router.get("", response_model=LabsOverview)
async def list_labs(session: Any = Depends(get_session)) -> LabsOverview:
    """Every marker with its results, newest marker first, plus the labs."""
    rows = await lab_repository.list_results(session)
    by_loinc: dict[str, list[LabResultRow]] = defaultdict(list)
    for row in rows:
        by_loinc[row.loinc_code].append(row)
    markers = [LabMarkerView(**_marker_fields(code, group)) for code, group in by_loinc.items()]
    markers.sort(key=lambda marker: (-marker.last_specimen_at.timestamp(), marker.name.lower()))
    return LabsOverview(
        markers=markers,
        labs=_sources(rows),
        count=len(markers),
        result_count=len(rows),
    )


@router.get("/{loinc}", response_model=LabMarkerDetail)
async def get_lab_marker(loinc: str, session: Any = Depends(get_session)) -> LabMarkerDetail:
    """One marker's results, oldest first, each with its lab and the lab's range."""
    if not is_valid_loinc(loinc):
        raise HTTPException(
            status_code=422,
            detail=f"{loinc!r} is not a valid LOINC code (like 2276-4; the check digit must match)",
        )
    rows = await lab_repository.list_results(session, loinc_code=loinc)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no lab results for LOINC {loinc}")
    fields = _marker_fields(loinc, rows)
    return LabMarkerDetail(
        **fields,
        gaps=_gap_views(rows),
        cross_match=await _cross_match(session, loinc, fields["name"], rows),
    )


async def _cross_match(
    session: Any, loinc: str, marker_name: str, rows: list[LabResultRow]
) -> LabCrossMatchView | None:
    """Fetch the paired wearable series per draw window, then let the engine read it."""
    pairing = engine.PAIRINGS.get(loinc)
    if pairing is None:
        return None
    wearable: dict[str, list[engine.WearableSample]] = defaultdict(list)
    seen: set[tuple[str, datetime]] = set()
    window = timedelta(days=engine.WINDOW_DAYS)
    for row in rows:
        points = await observation_repository.query_series(
            session,
            owner_id=DEFAULT_OWNER_ID,
            workspace_id=DEFAULT_WORKSPACE_ID,
            metric_id=pairing.metric_id,
            start=row.specimen_at - window,
            end=row.specimen_at,
        )
        for point in points:
            if point.value is None or point.stream_id is None:
                continue
            key = (str(point.stream_id), point.t)
            if key in seen:
                continue
            seen.add(key)
            wearable[str(point.stream_id)].append(engine.WearableSample(point.t, point.value))
    streams = await registry.list_streams(session, DEFAULT_OWNER_ID)
    labels = {str(s["id"]): s.get("device_label") or s["origin_key"] for s in streams}
    plugins = {str(s["id"]): s["source_plugin_id"] for s in streams}
    latest = max(rows, key=lambda r: r.specimen_at)
    match = engine.cross_match_card(
        loinc=loinc,
        marker_name=marker_name,
        points=[_point(row) for row in rows],
        pairing=pairing,
        wearable=wearable,
        stream_labels=labels,
        stream_plugins=plugins,
        lab_plugin_id=latest.source_plugin_id,
        marker_unit_label=display_unit(latest.canonical_unit),
    )
    return LabCrossMatchView(
        related_metric_id=pairing.metric_id,
        related_label=pairing.label,
        related_unit=pairing.unit,
        stream_id=match.stream_id,
        stream_label=labels.get(match.stream_id) if match.stream_id else None,
        card=match.card,
        reason=match.reason,
    )
