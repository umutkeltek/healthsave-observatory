"""``/api/v2/experiments/*`` — the n-of-1 experiment engine.

Closes the Insight Action Loop (ingest → understand → act → **measure**). The
read on-ramp (``GET /candidates``) ranks correlations as testable actions; the
rest of this surface lets a self-hoster *commit* to one and find out whether the
behavioural lever actually moved the outcome:

* ``GET  /candidates``                    — ranked correlation candidates + readiness verdict
* ``POST /``                              — create an experiment from a testable candidate
* ``GET  /``                              — list experiments (optional ``?status=``)
* ``GET  /{id}``                          — one experiment: definition + phase calendar + results
* ``POST /{id}/analyze``                  — (re)compute the controlled ABAB result now
* ``POST /{id}/abandon``                  — stop an experiment

The first v2 *write* surface for experiments — it follows the ``v2_agents``
precedent (repository write + ``session.commit()`` + 201). Discipline holds:
storage access goes through repository ports, the statistics are the pure
``analysis.statistical.experiments`` / ``experiment_readiness``, and the
``ExperimentRunner`` composes read → stats → write. No LLM here — results are
computed evidence.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from analysis.statistical.experiment_readiness import _short, classify_candidate
from analysis.statistical.experiments import (
    build_phase_calendar,
    progress,
)
from contracts._base import V2Model
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import briefing_repository, experiment_repository
from storage.ports import BriefingRepository, ExperimentRepository

from .deps import get_session, verify_api_key

_log = logging.getLogger("healthsave.api.v2_experiments")

router = APIRouter(prefix="/api/v2/experiments", dependencies=[Depends(verify_api_key)])

_CANDIDATES_LIMIT = 200
_STATUSES = frozenset({"collecting", "completed", "abandoned"})
_BRIEFING_REPO: BriefingRepository = briefing_repository()
_EXPERIMENT_REPO: ExperimentRepository = experiment_repository()


def _make_runner():
    """Build an ExperimentRunner bound to the app session factory.

    Lazy import keeps the analysis↔storage hop out of module load, and gives
    tests a single seam to monkeypatch (returning a stub runner) so route tests
    stay DB-free.
    """
    from analysis.experiments import ExperimentRunner

    from server.db.session import async_session

    return ExperimentRunner(async_session)


# ──────────────────────────────────────────────────────────────────────
# Wire models  (V2Model: extra='forbid'; owner/workspace sentinels dropped —
# single-user, like v2_agents)
# ──────────────────────────────────────────────────────────────────────


class CreateExperimentRequest(V2Model):
    lever_metric_id: str
    outcome_metric_id: str
    design: str = "ABAB"
    block_days: int = Field(default=7, ge=1, le=90)
    start_date: date | None = None  # defaults to today
    hypothesis: str | None = Field(default=None, max_length=2000)


class PhaseView(V2Model):
    label: str
    index: int
    start: date
    end: date


class ProgressView(V2Model):
    current_phase: str | None
    day_index: int
    total_days: int
    days_remaining: int
    is_complete: bool
    pct: float


class ResultView(V2Model):
    kind: str
    computed_at: datetime
    direction: str | None
    diff: float | None
    effect_size: float | None
    p_value: float | None
    inference: str | None
    summary: str | None
    n_a: int | None
    n_b: int | None
    mean_a: float | None
    mean_b: float | None
    n_blocks_used: int | None
    caveat: str | None
    adherence: dict[str, Any] | None


class ExperimentView(V2Model):
    id: UUID
    lever_metric_id: str
    outcome_metric_id: str
    lever: str  # human-readable tail (display convenience)
    outcome: str
    design: str
    block_days: int
    start_date: date
    hypothesis: str | None
    status: str
    created_at: datetime
    calendar: list[PhaseView]
    progress: ProgressView
    results: dict[str, ResultView]


class ExperimentListResponse(V2Model):
    experiments: list[ExperimentView]
    count: int


# ──────────────────────────────────────────────────────────────────────
# Mapping helpers
# ──────────────────────────────────────────────────────────────────────


def _result_view(row: Any) -> ResultView:
    """Storage result row → wire view, flattening the structured_data payload."""
    outcome = row.structured_data.get("outcome", {}) if row.structured_data else {}
    return ResultView(
        kind=row.kind,
        computed_at=row.computed_at,
        direction=row.direction,
        diff=row.diff,
        effect_size=row.effect_size,
        p_value=row.p_value,
        inference=row.inference,
        summary=row.summary,
        n_a=outcome.get("n_a"),
        n_b=outcome.get("n_b"),
        mean_a=outcome.get("mean_a"),
        mean_b=outcome.get("mean_b"),
        n_blocks_used=outcome.get("n_blocks_used"),
        caveat=outcome.get("caveat"),
        adherence=row.structured_data.get("adherence") if row.structured_data else None,
    )


def _experiment_view(
    row: Any,
    results: dict[str, Any],
    today: date,
) -> ExperimentView:
    calendar = build_phase_calendar(row.start_date, row.block_days, row.design)
    prog = progress(calendar, today)
    return ExperimentView(
        id=row.id,
        lever_metric_id=row.lever_metric_id,
        outcome_metric_id=row.outcome_metric_id,
        lever=_short(row.lever_metric_id),
        outcome=_short(row.outcome_metric_id),
        design=row.design,
        block_days=row.block_days,
        start_date=row.start_date,
        hypothesis=row.hypothesis,
        status=row.status,
        created_at=row.created_at,
        calendar=[
            PhaseView(label=p.label, index=p.index, start=p.start, end=p.end) for p in calendar
        ],
        progress=ProgressView(
            current_phase=prog.current_phase,
            day_index=prog.day_index,
            total_days=prog.total_days,
            days_remaining=prog.days_remaining,
            is_complete=prog.is_complete,
            pct=prog.pct,
        ),
        results={kind: _result_view(r) for kind, r in results.items()},
    )


def _today() -> date:
    return datetime.now(tz=UTC).date()


# ──────────────────────────────────────────────────────────────────────
# Candidates (read on-ramp — unchanged)
# ──────────────────────────────────────────────────────────────────────


def _abs_coefficient(structured_data: dict[str, Any]) -> float:
    coefficient = structured_data.get("coefficient")
    return abs(coefficient) if isinstance(coefficient, int | float) else 0.0


@router.get("/candidates")
async def list_candidates(session: AsyncSession = Depends(get_session)) -> dict:
    """Ranked correlation candidates annotated with experiment readiness.

    Strongest correlations first — the top of the list is the best candidate to
    promote into an experiment. Deduped to one row per metric pair (the strongest
    seen), since the same pair recurs across correlation runs.
    """
    findings = await _BRIEFING_REPO.fetch_correlations(session, limit=_CANDIDATES_LIMIT)

    # Dedupe by unordered pair, keeping the strongest |coefficient|.
    strongest: dict[frozenset[str], Any] = {}
    for row in findings:
        data = row.structured_data
        metric_a, metric_b = data.get("metric_a"), data.get("metric_b")
        if not metric_a or not metric_b:
            continue
        key = frozenset({metric_a, metric_b})
        current = strongest.get(key)
        if current is None or _abs_coefficient(data) > _abs_coefficient(current.structured_data):
            strongest[key] = row

    candidates: list[dict[str, Any]] = []
    for row in strongest.values():
        data = row.structured_data
        verdict = classify_candidate(data["metric_a"], data["metric_b"])
        candidates.append(
            {
                "metric_a": data["metric_a"],
                "metric_b": data["metric_b"],
                "coefficient": data.get("coefficient"),
                "method": data.get("method"),
                "period_days": data.get("period_days"),
                "p_value": data.get("p_value"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "readiness": {
                    "verdict": verdict.verdict,
                    "lever": verdict.lever,
                    "outcome": verdict.outcome,
                    "suggested_protocol": verdict.suggested_protocol,
                    "required_days": verdict.required_days,
                    "rationale": verdict.rationale,
                },
            }
        )

    candidates.sort(key=lambda c: abs(c["coefficient"] or 0), reverse=True)
    testable = sum(1 for c in candidates if c["readiness"]["verdict"] == "testable")
    return {"candidates": candidates, "count": len(candidates), "testable_count": testable}


# ──────────────────────────────────────────────────────────────────────
# Experiment lifecycle
# ──────────────────────────────────────────────────────────────────────


@router.post("", response_model=ExperimentView, status_code=201)
async def create_experiment(
    body: CreateExperimentRequest,
    session: AsyncSession = Depends(get_session),
) -> ExperimentView:
    """Create an experiment from a testable candidate.

    Validates the pair with the pure readiness classifier: the pair must be
    ``testable`` *and* the supplied ``lever_metric_id`` must actually be the
    controllable lever (not the outcome). On success the experiment is created
    and an immediate retrospective (observational) preview is computed over
    existing history — best-effort, so a thin-history install still creates the
    experiment cleanly.
    """
    verdict = classify_candidate(body.lever_metric_id, body.outcome_metric_id)
    if verdict.verdict != "testable":
        raise HTTPException(status_code=422, detail=verdict.rationale)
    if verdict.lever != body.lever_metric_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{_short(body.lever_metric_id)} isn't the controllable lever for this "
                f"pair — {verdict.rationale}"
            ),
        )

    start = body.start_date or _today()
    row = await _EXPERIMENT_REPO.create_experiment(
        session,
        lever_metric_id=body.lever_metric_id,
        outcome_metric_id=body.outcome_metric_id,
        design=body.design,
        block_days=body.block_days,
        start_date=start,
        hypothesis=body.hypothesis,
    )
    await session.commit()

    # Instant retrospective read over existing history (best-effort).
    try:
        await _make_runner().run_retrospective(row, as_of=_today())
    except Exception:  # pragma: no cover - defensive; creation must still succeed
        _log.warning("retrospective preview failed for experiment %s; continuing", row.id)

    results = await _EXPERIMENT_REPO.latest_results_by_kind(session, experiment_id=row.id)
    return _experiment_view(row, results, _today())


@router.get("", response_model=ExperimentListResponse)
async def list_experiments(
    session: AsyncSession = Depends(get_session),
    status: str | None = Query(default=None),
) -> ExperimentListResponse:
    """List experiments, newest first; optional ``?status=`` filter."""
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown status: {status!r}")

    rows = await _EXPERIMENT_REPO.list_experiments(session, status=status)
    today = _today()
    views: list[ExperimentView] = []
    for row in rows:
        results = await _EXPERIMENT_REPO.latest_results_by_kind(session, experiment_id=row.id)
        views.append(_experiment_view(row, results, today))
    return ExperimentListResponse(experiments=views, count=len(views))


@router.get("/{experiment_id}", response_model=ExperimentView)
async def get_experiment(
    experiment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentView:
    """One experiment: definition + phase calendar + progress + latest results."""
    row = await _EXPERIMENT_REPO.get_experiment(session, experiment_id=experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    results = await _EXPERIMENT_REPO.latest_results_by_kind(session, experiment_id=row.id)
    return _experiment_view(row, results, _today())


@router.post("/{experiment_id}/analyze", response_model=ExperimentView)
async def analyze_experiment(
    experiment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentView:
    """(Re)compute the controlled ABAB result now and return the refreshed view.

    Completes the experiment automatically once its window has fully elapsed.
    """
    row = await _EXPERIMENT_REPO.get_experiment(session, experiment_id=experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    await _make_runner().run_controlled(row, as_of=_today())

    # Re-read: status may have flipped to completed and a new result landed.
    row = await _EXPERIMENT_REPO.get_experiment(session, experiment_id=experiment_id)
    results = await _EXPERIMENT_REPO.latest_results_by_kind(session, experiment_id=experiment_id)
    return _experiment_view(row, results, _today())


@router.post("/{experiment_id}/abandon", response_model=ExperimentView)
async def abandon_experiment(
    experiment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ExperimentView:
    """Stop an experiment (status → abandoned)."""
    row = await _EXPERIMENT_REPO.set_status(
        session, experiment_id=experiment_id, status="abandoned"
    )
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    await session.commit()
    results = await _EXPERIMENT_REPO.latest_results_by_kind(session, experiment_id=experiment_id)
    return _experiment_view(row, results, _today())


__all__ = [
    "router",
    "CreateExperimentRequest",
    "ExperimentView",
    "ExperimentListResponse",
    "ResultView",
    "list_candidates",
    "create_experiment",
    "list_experiments",
    "get_experiment",
    "analyze_experiment",
    "abandon_experiment",
]
