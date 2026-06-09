"""GET ``/api/v2/metrics`` + ``/api/v2/metrics/{id}/series`` — the v2 read surface.

The single contract-first read API that both the standalone web dashboard and
the local LLM narrator query (Decision F: backend owns the ontology/series
shape; clients don't re-derive it). Additive, under the established
``/api/v2/`` namespace — no v1 surface touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from contracts.ontology import MetricDefinition, all_metrics, get_metric
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import time_series_query_service
from storage.ports import TimeSeriesQueryService

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2")

# Depend on the read port; storage.defaults hides production adapter selection.
_REPO: TimeSeriesQueryService = time_series_query_service()

RANGE_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
}


def _metric_summary(metric: MetricDefinition) -> dict:
    return {
        "id": metric.id,
        "display_name": metric.display_name,
        "category": metric.category,
        "value_type": metric.value_type,
        "canonical_unit": metric.canonical_unit,
    }


@router.get("/metrics")
async def list_metrics() -> list[dict]:
    """The full canonical metric catalog (ontology-driven, no DB hit)."""
    return [_metric_summary(metric) for metric in all_metrics()]


@router.get("/metrics/{metric_id}/series", dependencies=[Depends(verify_api_key)])
async def metric_series(
    metric_id: str,
    range: str = "7d",
    stream_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One metric's time-series over a multi-timescale window.

    ``stream_id`` optionally narrows the series to a single device stream
    (one physical emitter); omitted returns the fused series across all
    streams, unchanged.
    """
    metric = get_metric(metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail=f"unknown metric: {metric_id}")
    window = RANGE_WINDOWS.get(range)
    if window is None:
        raise HTTPException(
            status_code=422,
            detail=f"unknown range '{range}'; expected one of {sorted(RANGE_WINDOWS)}",
        )

    end = datetime.now(UTC)
    start = end - window
    points = await _REPO.query_series(
        session,
        owner_id=DEFAULT_OWNER_ID,
        workspace_id=DEFAULT_WORKSPACE_ID,
        metric_id=metric_id,
        start=start,
        end=end,
        stream_id=stream_id,
    )
    return {
        "metric": _metric_summary(metric),
        "range": range,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "points": [
            {
                "t": point.t.isoformat(),
                "value": point.value,
                "code": point.code,
                "unit": point.unit,
                "source_id": point.source_id,
                "stream_id": point.stream_id,
                "confidence": point.confidence,
            }
            for point in points
        ],
    }
