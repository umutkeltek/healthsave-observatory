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
from storage.defaults import briefing_repository
from storage.ports import BriefingRepository

from .deps import get_session, verify_api_key
from .insights import _record_trigger_run  # reuse the pipeline_runs ledger wrapper

router = APIRouter(prefix="/api/v2/insights", dependencies=[Depends(verify_api_key)])

_CORRELATIONS_LIMIT = 200
_FINDINGS_LIMIT = 200
_BRIEFING_REPO: BriefingRepository = briefing_repository()

# Finding kinds the evidence feed renders. Mirrors the finding_type values the
# analysis engine persists (see analysis.engine); an unknown ?type is a 422.
_EVIDENCE_TYPES = frozenset({"anomaly", "trend", "correlation", "summary", "recovery_score"})


def _narrative(row) -> dict | None:
    """Shape a NarrativeRow for the wire, or None when absent."""
    if row is None:
        return None
    return {
        "insight_type": row.insight_type,
        "narrative": row.narrative,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


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
    limit: int = Query(default=_CORRELATIONS_LIMIT, ge=1, le=_CORRELATIONS_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Persisted cross-metric correlation findings, newest first."""
    findings = await _BRIEFING_REPO.fetch_correlations(
        session, period_days=_validate_period(period), limit=limit
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


@router.get("/latest")
async def latest_narratives(session: AsyncSession = Depends(get_session)) -> dict:
    """Most recent daily-briefing + weekly-summary narratives (the weekly-brief card)."""
    narratives = await _BRIEFING_REPO.latest_narratives_by_type(
        session, insight_types=("daily_briefing", "weekly_summary")
    )
    return {
        "daily_briefing": _narrative(narratives.get("daily_briefing")),
        "weekly_summary": _narrative(narratives.get("weekly_summary")),
    }


@router.get("/findings")
async def list_findings(
    finding_type: str | None = Query(
        default=None,
        alias="type",
        description="Optional finding kind (anomaly / trend / correlation / summary).",
    ),
    limit: int = Query(default=_FINDINGS_LIMIT, ge=1, le=_FINDINGS_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Recent structured findings (the evidence feed), newest first.

    Each row carries its ``structured_data`` so the evidence card can show the
    calculation behind a finding (effect size, window, p-value, …). Optional
    ``?type=`` narrows to one kind.
    """
    if finding_type is not None and finding_type not in _EVIDENCE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown finding type: {finding_type}")
    rows = await _BRIEFING_REPO.fetch_findings(session, finding_type=finding_type, limit=limit)
    findings = [
        {
            "id": row.id,
            "finding_type": row.finding_type,
            "metric": row.metric,
            "severity": row.severity,
            "structured_data": row.structured_data,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return {"findings": findings, "count": len(findings)}


class TriggerBody(BaseModel):
    """v2 trigger request — extensible by ``type`` (correlation_analysis,
    recovery_check)."""

    type: str = "correlation_analysis"


@router.post("/trigger")
async def trigger(request: Request, body: TriggerBody | None = None) -> dict:
    """Run an analysis job on demand.

    Supports ``correlation_analysis`` and ``recovery_check``. Each checks its
    config block is enabled, runs the Brain-1 engine job inline through the
    pipeline_runs ledger, and reports completed vs skipped.
    """
    body = body or TriggerBody()
    analysis = request.app.state.analysis_config.analysis

    if body.type == "correlation_analysis":
        if not analysis.correlation_analysis.enabled:
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

    if body.type == "recovery_check":
        if not analysis.recovery.enabled:
            raise HTTPException(status_code=409, detail="recovery is disabled")
        run_id = await _record_trigger_run(
            request,
            job_kind="recovery_check",
            coro=request.app.state.analysis_engine.run_recovery_check(),
        )
        return {
            "status": "completed" if run_id is not None else "skipped",
            "run_type": "recovery_check",
            "run_id": run_id,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported type: {body.type}")
