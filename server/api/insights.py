"""GET /api/insights/* — Phase 1 stub routes.

These endpoints are structural scaffolding only. They return empty but
well-shaped responses so iOS / Grafana / dashboard clients can wire
against stable types now. The real implementations land in Phase 1.5
once the statistical engine and LLM narrator are connected.
"""

from fastapi import APIRouter, Depends

from ..models.insights import (
    AnomaliesListResponse,
    DailyBriefingResponse,
    InsightsLatestResponse,
    TrendsListResponse,
    TriggerResponse,
    WeeklySummaryResponse,
)
from .deps import verify_api_key

router = APIRouter(prefix="/api/insights", dependencies=[Depends(verify_api_key)])


@router.get("/latest", response_model=InsightsLatestResponse)
async def insights_latest() -> InsightsLatestResponse:
    """Return the most recent daily briefing, weekly summary, and findings."""
    return InsightsLatestResponse()


@router.get("/daily", response_model=DailyBriefingResponse)
async def insights_daily() -> DailyBriefingResponse:
    """Return today's daily briefing narrative."""
    return DailyBriefingResponse()


@router.get("/weekly", response_model=WeeklySummaryResponse)
async def insights_weekly() -> WeeklySummaryResponse:
    """Return the current week's summary narrative."""
    return WeeklySummaryResponse()


@router.get("/anomalies", response_model=AnomaliesListResponse)
async def insights_anomalies() -> AnomaliesListResponse:
    """Return recent anomaly detections."""
    return AnomaliesListResponse()


@router.get("/trends", response_model=TrendsListResponse)
async def insights_trends() -> TrendsListResponse:
    """Return recent trend analyses."""
    return TrendsListResponse()


@router.post("/trigger", response_model=TriggerResponse)
async def insights_trigger() -> TriggerResponse:
    """Kick off an ad-hoc analysis run (stub — no-op in Phase 1)."""
    return TriggerResponse(
        status="accepted",
        run_type=None,
        message="Analysis engine scaffolding only — no run performed in Phase 1.",
    )
