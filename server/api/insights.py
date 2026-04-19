"""GET/POST /api/insights/* — Phase 2 activation.

``/latest`` reads the most-recent ``analysis_insights`` row per
``insight_type`` from TimescaleDB. ``/anomalies`` now returns real
anomaly findings from ``analysis_findings`` where
``finding_type='anomaly'``, optionally filtered by ``since`` and
``severity`` query parameters. ``/trigger`` runs the daily briefing
inline against the engine stashed on ``app.state``. Daily/weekly/trends
stay stubbed until their engine methods land.
"""

from __future__ import annotations

import json
from typing import get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.types import Severity

from ..models.insights import (
    AnomaliesListResponse,
    AnomalyResponse,
    DailyBriefingResponse,
    InsightsLatestResponse,
    TrendsListResponse,
    TriggerRequest,
    TriggerResponse,
    WeeklySummaryResponse,
)
from .deps import get_session, verify_api_key

_ALLOWED_SEVERITIES = frozenset(get_args(Severity))
_ANOMALIES_LIMIT = 200

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
async def insights_anomalies(
    since: str | None = Query(default=None, description="ISO-8601 lower bound on created_at"),
    severity: str | None = Query(
        default=None,
        description="Comma-separated list: info, watch, alert",
    ),
    session: AsyncSession = Depends(get_session),
) -> AnomaliesListResponse:
    """Return recent anomaly findings from the analysis engine.

    Reads ``analysis_findings`` where ``finding_type='anomaly'``, ordered
    by ``created_at DESC``. Optional ``since`` limits rows to those
    created at-or-after the timestamp. Optional ``severity`` is a
    comma-separated list (``info,watch,alert``) matched against the
    finding's severity column.
    """
    where_clauses = ["finding_type = 'anomaly'"]
    params: dict[str, object] = {}

    if since is not None:
        where_clauses.append("created_at >= :since")
        params["since"] = since

    if severity is not None:
        requested = {s.strip() for s in severity.split(",") if s.strip()}
        filtered = sorted(requested & _ALLOWED_SEVERITIES)
        if filtered:
            where_clauses.append("severity = ANY(:severities)")
            params["severities"] = filtered

    params["limit"] = _ANOMALIES_LIMIT

    sql = f"""
        SELECT id, metric, severity, structured_data, created_at
        FROM analysis_findings
        WHERE {" AND ".join(where_clauses)}
        ORDER BY created_at DESC
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    rows = result.fetchall() if hasattr(result, "fetchall") else list(result)

    anomalies: list[AnomalyResponse] = []
    for row in rows:
        data = row.structured_data or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        anomalies.append(
            AnomalyResponse(
                id=row.id,
                metric=row.metric or data.get("metric"),
                severity=row.severity,
                magnitude=data.get("magnitude"),
                direction=data.get("direction"),
                detected_at=data.get("detected_at") or row.created_at,
                context=data.get("context") or {},
            )
        )
    return AnomaliesListResponse(anomalies=anomalies, count=len(anomalies))


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
