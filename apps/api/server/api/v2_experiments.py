"""GET ``/api/v2/experiments/candidates`` — ranked n-of-1 experiment candidates.

Closes the Insight Action Loop (ingest → understand → **act**): turns the
correlation engine's ranked findings into "what to try next". Each persisted
correlation is annotated with an experiment-readiness verdict — which metric is
the behavioral lever, which the outcome, a suggested ABAB protocol — by the pure
:mod:`analysis.statistical.experiment_readiness` classifier.

Read-only and additive. There is deliberately **no** ``ExperimentRepository``,
no experiments table, and no ABAB significance engine yet — those land with the
full experiment runtime. This endpoint is the on-ramp: it ranks correlations as
actions and says which are testable, without committing to running them.
"""

from __future__ import annotations

from typing import Any

from analysis.statistical.experiment_readiness import classify_candidate
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import briefings

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2/experiments", dependencies=[Depends(verify_api_key)])

_CANDIDATES_LIMIT = 200


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
    findings = await briefings.fetch_correlations(session, limit=_CANDIDATES_LIMIT)

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
