"""v2 Labs read API — blood test results as a first-class source (Labs slice 1).

``GET /api/v2/labs`` lists every marker with its results and the labs (streams)
they came from; ``GET /api/v2/labs/{loinc}`` returns one marker's series.

Each result carries the reference range the lab printed for it. Results from
different labs stay separate rows tagged with their stream; nothing here
averages across labs. The SQL lives in ``storage.timescale.labs``; this module
only shapes responses (typed, additive v2).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from contracts._base import V2Model
from fastapi import APIRouter, Depends, HTTPException
from normalization.labs import FLAG_DATE_ONLY, display_unit, is_valid_loinc, metric_id_for
from storage.timescale.labs import LabResultRow
from storage.timescale.labs import default_repository as lab_repository

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


class LabsOverview(V2Model):
    markers: list[LabMarkerView]
    labs: list[LabSourceView]
    count: int
    result_count: int


class LabMarkerDetail(LabMarkerView):
    pass


def _result_view(row: LabResultRow) -> LabResultView:
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
    )


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
    return LabMarkerDetail(**_marker_fields(loinc, rows))
