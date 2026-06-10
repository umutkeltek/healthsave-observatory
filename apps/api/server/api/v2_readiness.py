"""GET ``/api/v2/readiness`` — data coverage + analyzability (Insight Action Loop card #1).

Answers the first question a self-hoster actually has: *"is my data even good
enough, and what can I analyze right now?"* For every metric in the canonical
store it reports coverage (count, distinct days, first/last observation) and
grades that against the same data-sufficiency gates the analysis engine uses, so
the card can say "trend analysis ready" or "needs 6 more days" per metric. It
also surfaces source attribution + freshness up top — deliberately, because
Apple HealthKit can't sync while the device is locked, so coverage is genuinely
uncertain and should be the headline, not a hidden footnote.

Additive v2 read — no v1 surface touched. The SQL lives in
the storage adapter; this route only assembles + grades, and the grading is the
pure ``analysis.statistical.gates`` engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from analysis.statistical.gates import check_sufficiency
from analysis.types import DataSummary
from contracts.ontology import get_metric
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import readiness_repository
from storage.ports import ReadinessRepository

from .deps import get_session, verify_api_key
from .swr import v2_read_cache

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])
_READINESS_REPO: ReadinessRepository = readiness_repository()

# The gates a single metric's coverage can actually evaluate: total
# observations + distinct days. correlation/recovery need cross-metric or
# per-session inputs one metric's coverage can't express, so they're
# intentionally not graded here (the gate would raise — see gates.py).
_PER_METRIC_GATES: tuple[str, ...] = ("anomaly_detection", "trend_analysis")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    """The more-recent of two optional timestamps (None is "no value")."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _grade(summary: DataSummary) -> dict[str, Any]:
    """Run each per-metric sufficiency gate and shape the verdict for the wire."""
    graded: dict[str, Any] = {}
    for analysis_type in _PER_METRIC_GATES:
        result = check_sufficiency(analysis_type, summary)
        graded[analysis_type] = {
            "is_sufficient": result.is_sufficient,
            "missing": result.missing_description,
            "days_until_sufficient": result.days_until_sufficient,
        }
    return graded


@router.get("/readiness")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict:
    """Per-metric coverage + analyzability, plus source attribution and freshness."""
    # Both aggregates walk the whole canonical store — served through the
    # process-level SWR cache so the scan runs at most once per TTL, not per
    # page load (the live 2M-row store took 5-20s per request).
    coverage = await v2_read_cache.get(
        "canonical_coverage", lambda: _READINESS_REPO.fetch_canonical_coverage(session)
    )
    sources = await v2_read_cache.get(
        "canonical_sources", lambda: _READINESS_REPO.fetch_canonical_sources(session)
    )

    metrics: list[dict[str, Any]] = []
    last_observation_at: datetime | None = None
    last_ingested_at: datetime | None = None

    for row in coverage:
        metric = get_metric(row["metric_id"])
        summary = DataSummary(
            metric=row["metric_id"],
            observation_count=row["observation_count"],
            days_with_data=row["days_with_data"],
            first_observation=row["first_observation_at"],
            last_observation=row["last_observation_at"],
        )
        metrics.append(
            {
                "metric_id": row["metric_id"],
                "display_name": metric.display_name if metric is not None else row["metric_id"],
                "category": metric.category if metric is not None else None,
                "observation_count": row["observation_count"],
                "days_with_data": row["days_with_data"],
                "first_observation_at": _iso(row["first_observation_at"]),
                "last_observation_at": _iso(row["last_observation_at"]),
                "analyzable": _grade(summary),
            }
        )
        last_observation_at = _later(last_observation_at, row["last_observation_at"])
        last_ingested_at = _later(last_ingested_at, row["last_ingested_at"])

    return {
        "as_of": datetime.now(tz=UTC).isoformat(),
        "last_observation_at": _iso(last_observation_at),
        "last_ingested_at": _iso(last_ingested_at),
        "sources": [
            {
                "source_plugin_id": source["source_plugin_id"],
                "observation_count": source["observation_count"],
                "last_ingested_at": _iso(source["last_ingested_at"]),
            }
            for source in sources
        ],
        "metrics": metrics,
        "summary": {"metrics_with_data": len(metrics)},
    }
