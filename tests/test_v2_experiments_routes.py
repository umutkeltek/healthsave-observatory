"""Tests for GET /api/v2/experiments/candidates.

FakeSession discipline — no live DB. The route reads correlation findings via
briefings.fetch_correlations (real SQL over the fake session) and annotates each
with the experiment-readiness classifier. Asserts the readiness annotation,
strongest-first ranking, dedupe-by-pair, and testable_count.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.v2_experiments import list_candidates  # noqa: E402


class _Row(SimpleNamespace):
    pass


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return _Result(self._rows)


def _corr(row_id, metric_a, metric_b, coefficient, *, created=datetime(2026, 5, 1, tzinfo=UTC)):
    return _Row(
        id=row_id,
        metric=f"{metric_a}~{metric_b}",
        severity=None,
        structured_data={
            "metric_a": metric_a,
            "metric_b": metric_b,
            "coefficient": coefficient,
            "method": "spearman",
            "period_days": 90,
            "p_value": 0.01,
        },
        created_at=created,
    )


@pytest.mark.asyncio
async def test_candidates_annotates_readiness_and_ranks_strongest_first():
    rows = [
        _corr(1, "activity.steps", "vital.resting_heart_rate", 0.40),
        _corr(2, "vital.hrv_sdnn", "vital.resting_heart_rate", -0.82),
        _corr(3, "activity.active_energy", "vital.resting_heart_rate", 0.55),
    ]
    session = _Session(rows)

    result = await list_candidates(session=session)

    assert result["count"] == 3
    assert result["testable_count"] == 2  # the two activity↔vital pairs

    # Strongest |coefficient| first: HRV~RHR (0.82) → active_energy~RHR (0.55) → steps~RHR (0.40).
    coeffs = [abs(c["coefficient"]) for c in result["candidates"]]
    assert coeffs == sorted(coeffs, reverse=True)

    top = result["candidates"][0]
    assert {top["metric_a"], top["metric_b"]} == {"vital.hrv_sdnn", "vital.resting_heart_rate"}
    assert top["readiness"]["verdict"] == "not_controllable"  # both physiological

    steps = next(
        c for c in result["candidates"] if "activity.steps" in (c["metric_a"], c["metric_b"])
    )
    assert steps["readiness"]["verdict"] == "testable"
    assert steps["readiness"]["lever"] == "activity.steps"
    assert steps["readiness"]["required_days"] == 28


@pytest.mark.asyncio
async def test_candidates_dedupe_keeps_strongest_per_pair():
    rows = [
        _corr(1, "activity.steps", "vital.resting_heart_rate", 0.40),
        _corr(2, "activity.steps", "vital.resting_heart_rate", 0.61),  # same pair, stronger
    ]
    session = _Session(rows)

    result = await list_candidates(session=session)

    assert result["count"] == 1
    assert result["candidates"][0]["coefficient"] == 0.61


@pytest.mark.asyncio
async def test_candidates_skips_malformed_rows():
    bad = _Row(
        id=9,
        metric="?",
        severity=None,
        structured_data={"coefficient": 0.9},  # no metric_a/metric_b
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    session = _Session([bad])

    result = await list_candidates(session=session)

    assert result == {"candidates": [], "count": 0, "testable_count": 0}


@pytest.mark.asyncio
async def test_candidates_empty_store():
    session = _Session([])
    result = await list_candidates(session=session)
    assert result == {"candidates": [], "count": 0, "testable_count": 0}
    sql, _ = session.calls[0]
    assert "finding_type = 'correlation'" in sql
