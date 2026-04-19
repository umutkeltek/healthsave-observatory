"""GET/POST /api/insights/* — Phase 1.5 activation.

``/latest`` now reads the most-recent ``analysis_insights`` row per
``insight_type`` from TimescaleDB and returns real narrative data.
``/trigger`` runs the daily briefing inline against the engine stashed
on ``app.state``. The other routes (daily/weekly/anomalies/trends)
remain stubs — Phase 2 will light them up alongside the corresponding
engine methods.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.insights import (
    AnomaliesListResponse,
    DailyBriefingResponse,
    InsightsLatestResponse,
    TrendsListResponse,
    TriggerRequest,
    TriggerResponse,
    WeeklySummaryResponse,
)
from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/insights", dependencies=[Depends(verify_api_key)])


@router.get("/latest", response_model=InsightsLatestResponse)
async def insights_latest(
    session: AsyncSession = Depends(get_session),
) -> InsightsLatestResponse:
    """Return the most recent daily briefing + weekly summary narratives."""
    result = await session.execute(
        text(
            """
            SELECT DISTINCT ON (insight_type)
                insight_type, narrative, created_at
            FROM analysis_insights
            WHERE insight_type IN ('daily_briefing', 'weekly_summary')
            ORDER BY insight_type, created_at DESC
            """
        )
    )
    rows = {row.insight_type: row for row in result}
    daily = rows.get("daily_briefing")
    weekly = rows.get("weekly_summary")
    return InsightsLatestResponse(
        daily_briefing=DailyBriefingResponse(
            narrative=daily.narrative,
            created_at=daily.created_at,
        )
        if daily is not None
        else None,
        weekly_summary=WeeklySummaryResponse(
            narrative=weekly.narrative,
            created_at=weekly.created_at,
        )
        if weekly is not None
        else None,
    )


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
async def insights_trigger(
    request: Request,
    body: TriggerRequest | None = None,
) -> TriggerResponse:
    """Run an ad-hoc analysis job inline.

    Only ``daily_briefing`` is supported in Phase 1.5. The call runs
    synchronously against ``app.state.analysis_engine`` — fine for the
    one active job. Future job types (weekly, anomaly, etc.) should
    dispatch via ``request.app.state.scheduler`` once their engine
    methods land.
    """
    body = body or TriggerRequest()
    if body.type == "daily_briefing":
        if not request.app.state.analysis_config.analysis.daily_briefing.enabled:
            raise HTTPException(status_code=409, detail="daily_briefing is disabled")
        # Engine returns a run_id on completion, None when the run was
        # skipped (no data). Both cases are successful, just distinct.
        run_id = await request.app.state.analysis_engine.run_daily_briefing()
        return TriggerResponse(
            status="completed" if run_id is not None else "skipped",
            run_type="daily_briefing",
            run_id=run_id,
        )
    raise HTTPException(status_code=400, detail=f"Unsupported type: {body.type}")
