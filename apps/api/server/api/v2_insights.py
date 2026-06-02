"""``GET /api/v2/insights/correlations`` + ``POST /api/v2/insights/trigger``.

The additive v2 read surface for the analysis *output* clients consume. The
frozen v1 ``/api/insights/*`` surface is untouched; new insight surfaces land
under ``/api/v2/`` (see ``AGENTS.md`` — new client-facing reads go to v2). Plain
``dict`` responses, matching the v2 metrics read convention.

Correlations are returned newest-first; within a single run they were persisted
strongest-first (the n-of-1 experiment candidate order).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import briefings

from .deps import get_session, verify_api_key
from .insights import _record_trigger_run  # reuse the pipeline_runs ledger wrapper

router = APIRouter(prefix="/api/v2/insights", dependencies=[Depends(verify_api_key)])

_CORRELATIONS_LIMIT = 200


def _validate_period(period: str | None) -> str | None:
    """Return the leading day-count of a ``30d``/``90d`` period, or None."""
    if period is None:
        return None
    if not period.endswith("d") or not period[:-1].isdigit() or int(period[:-1]) <= 0:
        raise HTTPException(status_code=422, detail="Invalid period; expected format like 90d")
    return period[:-1]


@router.get("/correlations")
async def list_correlations(
    period: str | None = Query(default=None, description="Optional day window such as 30d or 90d"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Persisted cross-metric correlation findings, newest first."""
    findings = await briefings.fetch_correlations(
        session, period_days=_validate_period(period), limit=_CORRELATIONS_LIMIT
    )
    correlations = [
        {
            "metric_a": row.structured_data.get("metric_a"),
            "metric_b": row.structured_data.get("metric_b"),
            "coefficient": row.structured_data.get("coefficient"),
            "method": row.structured_data.get("method"),
            "period_days": row.structured_data.get("period_days"),
            "p_value": row.structured_data.get("p_value"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in findings
    ]
    return {"correlations": correlations, "count": len(correlations)}


class TriggerBody(BaseModel):
    """v2 trigger request — extensible by ``type`` (correlation_analysis today)."""

    type: str = "correlation_analysis"


@router.post("/trigger")
async def trigger(request: Request, body: TriggerBody | None = None) -> dict:
    """Run an analysis job on demand. Currently supports ``correlation_analysis``."""
    body = body or TriggerBody()
    if body.type != "correlation_analysis":
        raise HTTPException(status_code=400, detail=f"Unsupported type: {body.type}")
    if not request.app.state.analysis_config.analysis.correlation_analysis.enabled:
        raise HTTPException(status_code=409, detail="correlation_analysis is disabled")

    findings = await _record_trigger_run(
        request,
        job_kind="correlation_analysis",
        coro=request.app.state.analysis_engine.run_correlation_analysis(),
    )
    return {
        "status": "completed" if findings else "skipped",
        "run_type": "correlation_analysis",
        "count": len(findings),
    }
