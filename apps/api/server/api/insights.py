"""GET/POST /api/insights/* - Phase 2 activation.

``/latest`` reads the most-recent ``analysis_insights`` row per
``insight_type`` from TimescaleDB. ``/anomalies`` now returns real
anomaly findings from ``analysis_findings`` where
``finding_type='anomaly'``, optionally filtered by ``since`` and
``severity`` query parameters. ``/trends`` returns persisted trend
findings, optionally filtered by period. ``/trigger`` runs supported
analysis jobs inline against the engine stashed on ``app.state``. Daily
and weekly remain stubs until their historical lookup methods land.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, get_args

from analysis.types import Severity
from compat_v1.models import (
    AnomaliesListResponse,
    AnomalyResponse,
    DailyBriefingResponse,
    InsightsLatestResponse,
    RunsListResponse,
    RunSummaryResponse,
    TrendResponse,
    TrendsListResponse,
    TriggerRequest,
    TriggerResponse,
    WeeklySummaryResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import briefings
from storage.timescale import runs as pipeline_runs

from .deps import get_session, verify_api_key

_log = logging.getLogger("healthsave.api.insights")


async def _record_trigger_run(request: Request, *, job_kind: str, coro: Awaitable[Any]) -> Any:
    """Write claim → run → mark for one inline trigger invocation.

    Reads the session factory off ``app.state.session_factory`` (set
    by the lifespan in ``server.main``). When absent (e.g. unit tests
    that pass a SimpleNamespace request), the helper degrades to
    just awaiting the coroutine — the ledger gets nothing, but the
    trigger still runs. Production always has the factory.
    """
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return await coro

    idempotency_key = f"{job_kind}:api:{uuid.uuid4().hex[:12]}"
    record_id: int | None = None

    async with session_factory() as session:
        try:
            record_id = await pipeline_runs.claim_run(
                session,
                job_kind=job_kind,
                idempotency_key=idempotency_key,
                triggered_by="api",
            )
            await session.commit()
        except Exception:
            await session.rollback()
            _log.exception("failed to claim pipeline_run for %s", job_kind)

    try:
        result = await coro
    except Exception as exc:
        if record_id is not None:
            async with session_factory() as session:
                try:
                    await pipeline_runs.mark_failed(session, run_id=record_id, error=str(exc))
                    await session.commit()
                except Exception:
                    await session.rollback()
                    _log.exception("failed to mark pipeline_run as failed")
        raise

    if record_id is not None:
        async with session_factory() as session:
            try:
                await pipeline_runs.mark_succeeded(
                    session,
                    run_id=record_id,
                    result=_summarize_trigger_result(result),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                _log.exception("failed to mark pipeline_run as succeeded")

    return result


def _summarize_trigger_result(result: Any) -> dict[str, Any] | None:
    """Project an engine return value into a JSON-serializable summary."""
    if result is None:
        return None
    if isinstance(result, int):
        return {"engine_run_id": result}
    if isinstance(result, list):
        return {"items_count": len(result)}
    return {"repr": repr(result)[:1000]}


_ALLOWED_SEVERITIES = frozenset(get_args(Severity))
_ANOMALIES_LIMIT = 200
_TRENDS_LIMIT = 200
_RUNS_LIMIT = 200

router = APIRouter(prefix="/api/insights", dependencies=[Depends(verify_api_key)])


@router.get("/latest", response_model=InsightsLatestResponse)
async def insights_latest(
    session: AsyncSession = Depends(get_session),
) -> InsightsLatestResponse:
    """Return the most recent daily briefing + weekly summary narratives."""
    rows = await briefings.latest_narratives_by_type(
        session, insight_types=("daily_briefing", "weekly_summary")
    )
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
    since: datetime | str | None = Query(
        default=None, description="ISO-8601 lower bound on created_at"
    ),
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
    finding's severity column. SQL lives in
    ``storage.timescale.briefings`` — this handler does parameter
    validation and wire-shape mapping only.
    """
    if isinstance(since, str):
        try:
            since = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid since timestamp") from exc

    severities: frozenset[str] | None = None
    if severity is not None:
        requested = {s.strip().lower() for s in severity.split(",") if s.strip()}
        unknown = requested - _ALLOWED_SEVERITIES
        if unknown:
            allowed = ", ".join(sorted(_ALLOWED_SEVERITIES))
            raise HTTPException(
                status_code=422,
                detail=f"Invalid severity: {', '.join(sorted(unknown))}. Allowed: {allowed}",
            )
        if requested:
            severities = frozenset(requested)

    findings = await briefings.fetch_anomalies(
        session, since=since, severities=severities, limit=_ANOMALIES_LIMIT
    )
    anomalies = [
        AnomalyResponse(
            id=row.id,
            metric=row.metric or row.structured_data.get("metric"),
            severity=row.severity,
            magnitude=row.structured_data.get("magnitude"),
            direction=row.structured_data.get("direction"),
            detected_at=row.structured_data.get("detected_at") or row.created_at,
            context=row.structured_data.get("context") or {},
        )
        for row in findings
    ]
    return AnomaliesListResponse(anomalies=anomalies, count=len(anomalies))


@router.get("/trends", response_model=TrendsListResponse)
async def insights_trends(
    period: str | None = Query(
        default=None,
        description="Optional day period filter such as 30d or 90d",
    ),
    session: AsyncSession = Depends(get_session),
) -> TrendsListResponse:
    """Return recent trend findings from the analysis engine.

    SQL lives in ``storage.timescale.briefings`` — this handler does
    parameter validation (period format) and wire-shape mapping only.
    """
    period_days: str | None = None
    if period is not None:
        if not period.endswith("d") or not period[:-1].isdigit() or int(period[:-1]) <= 0:
            raise HTTPException(status_code=422, detail="Invalid period; expected format like 30d")
        period_days = period[:-1]

    findings = await briefings.fetch_trends(session, period_days=period_days, limit=_TRENDS_LIMIT)
    trends = [
        TrendResponse(
            metric=row.metric or row.structured_data.get("metric"),
            slope=row.structured_data.get("slope"),
            direction=row.structured_data.get("direction"),
            period_days=row.structured_data.get("period_days"),
            p_value=row.structured_data.get("p_value"),
            confidence=row.structured_data.get("confidence"),
        )
        for row in findings
    ]
    return TrendsListResponse(trends=trends, count=len(trends))


@router.post("/trigger", response_model=TriggerResponse)
async def insights_trigger(
    request: Request,
    body: TriggerRequest | None = None,
) -> TriggerResponse:
    """Run an ad-hoc analysis job inline.

    ``daily_briefing`` and ``trend_analysis`` run synchronously against
    ``app.state.analysis_engine``. Future long-running job types
    (weekly, correlation, etc.) should dispatch to the ``apps/worker``
    service via a Postgres NOTIFY queue rather than running inline —
    the API process no longer carries a scheduler in v2.
    """
    body = body or TriggerRequest()
    if body.type == "daily_briefing":
        if not request.app.state.analysis_config.analysis.daily_briefing.enabled:
            raise HTTPException(status_code=409, detail="daily_briefing is disabled")
        # Engine returns a run_id on completion, None when the run was
        # skipped (no data). Both cases are successful, just distinct.
        # Phase 4D: also writes a pipeline_runs row (triggered_by='api').
        run_id = await _record_trigger_run(
            request,
            job_kind="daily_briefing",
            coro=request.app.state.analysis_engine.run_daily_briefing(),
        )
        return TriggerResponse(
            status="completed" if run_id is not None else "skipped",
            run_type="daily_briefing",
            run_id=run_id,
        )
    if body.type == "trend_analysis":
        if not request.app.state.analysis_config.analysis.trend_analysis.enabled:
            raise HTTPException(status_code=409, detail="trend_analysis is disabled")
        findings = await _record_trigger_run(
            request,
            job_kind="trend_analysis",
            coro=request.app.state.analysis_engine.run_trend_analysis(),
        )
        return TriggerResponse(
            status="completed" if findings else "skipped",
            run_type="trend_analysis",
            message=f"{len(findings)} trend findings persisted",
        )
    raise HTTPException(status_code=400, detail=f"Unsupported type: {body.type}")


@router.get("/runs", response_model=RunsListResponse)
async def insights_runs(
    job_kind: str | None = Query(
        default=None,
        description="Filter to a specific scheduler job (e.g. 'daily_briefing').",
    ),
    limit: int = Query(default=100, ge=1, le=_RUNS_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> RunsListResponse:
    """Recent rows from the pipeline_runs ledger.

    The ledger is written by the ``apps/worker`` APScheduler listener
    (Phase 4B). This route is the read-side surface — newest first,
    optional ``job_kind`` filter, capped at 200 per request.

    Status values: pending, running, succeeded, failed, cancelled,
    skipped. ``triggered_by`` is one of: scheduler, manual, api, event.
    """
    rows = await pipeline_runs.fetch_recent(session, job_kind=job_kind, limit=limit)
    summaries = [
        RunSummaryResponse(
            id=r.id,
            job_kind=r.job_kind,
            status=r.status,
            started_at=r.started_at,
            ended_at=r.ended_at,
            error=r.error,
            attempt=r.attempt,
            triggered_by=r.triggered_by,
        )
        for r in rows
    ]
    return RunsListResponse(runs=summaries, count=len(summaries))
