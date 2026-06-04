"""Tests for the /api/v2/experiments surface.

FakeSession discipline — no live DB. The candidates route reads correlation
findings via the briefing repository; the lifecycle routes
(create/list/detail/analyze/abandon) are tested by stubbing the storage repo +
the ExperimentRunner so the route logic — validation, view shaping, status
handling, 404/422 — is exercised without a DB.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.api.v2_experiments as v2x  # noqa: E402
from server.api.v2_experiments import (  # noqa: E402
    CreateExperimentRequest,
    abandon_experiment,
    analyze_experiment,
    create_experiment,
    get_experiment,
    list_candidates,
    list_experiments,
)
from storage.timescale.experiments import ExperimentResultRow, ExperimentRow  # noqa: E402

EXP_ID = UUID("11111111-1111-1111-1111-111111111111")


# ──────────────────────────────────────────────────────────────────────
# Candidates (read on-ramp) — fake session running real briefings SQL
# ──────────────────────────────────────────────────────────────────────


class _Row(SimpleNamespace):
    pass


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []
        self.committed = False

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return _Result(self._rows)

    async def commit(self):
        self.committed = True


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
    result = await list_candidates(session=_Session(rows))

    assert result["count"] == 3
    assert result["testable_count"] == 2

    coeffs = [abs(c["coefficient"]) for c in result["candidates"]]
    assert coeffs == sorted(coeffs, reverse=True)

    top = result["candidates"][0]
    assert {top["metric_a"], top["metric_b"]} == {"vital.hrv_sdnn", "vital.resting_heart_rate"}
    assert top["readiness"]["verdict"] == "not_controllable"

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
        _corr(2, "activity.steps", "vital.resting_heart_rate", 0.61),
    ]
    result = await list_candidates(session=_Session(rows))
    assert result["count"] == 1
    assert result["candidates"][0]["coefficient"] == 0.61


@pytest.mark.asyncio
async def test_candidates_skips_malformed_rows():
    bad = _Row(
        id=9,
        metric="?",
        severity=None,
        structured_data={"coefficient": 0.9},
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    result = await list_candidates(session=_Session([bad]))
    assert result == {"candidates": [], "count": 0, "testable_count": 0}


@pytest.mark.asyncio
async def test_candidates_empty_store():
    session = _Session([])
    result = await list_candidates(session=session)
    assert result == {"candidates": [], "count": 0, "testable_count": 0}
    assert session.calls  # the SQL ran


# ──────────────────────────────────────────────────────────────────────
# Lifecycle — stubbed storage repo + runner
# ──────────────────────────────────────────────────────────────────────


def _experiment_row(**overrides) -> ExperimentRow:
    base = dict(
        id=EXP_ID,
        lever_metric_id="activity.steps",
        outcome_metric_id="vital.resting_heart_rate",
        design="ABAB",
        block_days=7,
        start_date=date(2026, 6, 2),
        hypothesis="More steps lower my RHR",
        status="collecting",
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
        updated_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    base.update(overrides)
    return ExperimentRow(**base)


def _result_row(kind="controlled", **overrides) -> ExperimentResultRow:
    base = dict(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        experiment_id=EXP_ID,
        kind=kind,
        computed_at=datetime(2026, 7, 1, tzinfo=UTC),
        direction="decrease",
        diff=-3.2,
        effect_size=-0.7,
        p_value=0.08,
        inference="randomization_test",
        summary="resting heart rate was 3.2 lower during intervention blocks",
        structured_data={
            "outcome": {"n_a": 14, "n_b": 14, "mean_a": 60.0, "mean_b": 56.8, "caveat": "…"},
            "adherence": {"status": "strong"},
        },
    )
    base.update(overrides)
    return ExperimentResultRow(**base)


class _StubStore:
    """Configurable stand-in for ExperimentRepository (records calls)."""

    def __init__(self, *, created=None, got=..., listing=None, set_result=..., results=None):
        self._created = created
        self._got = got
        self._listing = listing or []
        self._set_result = set_result
        self._results = results or {}
        self.created_kw: dict | None = None
        self.list_status: str | None = "UNSET"
        self.set_call: tuple | None = None

    async def create_experiment(self, session, **kw):
        self.created_kw = kw
        return self._created

    async def get_experiment(self, session, *, experiment_id, **kw):
        return self._got

    async def list_experiments(self, session, *, status=None, **kw):
        self.list_status = status
        return self._listing

    async def set_status(self, session, *, experiment_id, status, **kw):
        self.set_call = (experiment_id, status)
        return self._set_result

    async def latest_results_by_kind(self, session, *, experiment_id):
        return self._results


class _StubRunner:
    def __init__(self):
        self.retrospective_called = False
        self.controlled_called = False

    async def run_retrospective(self, experiment, *, as_of, **kw):
        self.retrospective_called = True
        return None

    async def run_controlled(self, experiment, *, as_of, **kw):
        self.controlled_called = True
        return None


@pytest.fixture
def wire(monkeypatch):
    """Install a stub store + runner into the route module; return both."""

    def install(store: _StubStore) -> _StubRunner:
        runner = _StubRunner()
        monkeypatch.setattr(v2x, "_EXPERIMENT_REPO", store)
        monkeypatch.setattr(v2x, "_make_runner", lambda: runner)
        return runner

    return install


@pytest.mark.asyncio
async def test_create_validates_and_runs_retrospective(wire):
    store = _StubStore(
        created=_experiment_row(), results={"retrospective": _result_row("retrospective")}
    )
    runner = wire(store)
    session = _Session()

    body = CreateExperimentRequest(
        lever_metric_id="activity.steps",
        outcome_metric_id="vital.resting_heart_rate",
        start_date=date(2026, 6, 2),
    )
    view = await create_experiment(body=body, session=session)

    assert view.id == EXP_ID and view.lever == "steps" and view.outcome == "resting heart rate"
    assert view.status == "collecting"
    assert store.created_kw["lever_metric_id"] == "activity.steps"
    assert store.created_kw["design"] == "ABAB" and store.created_kw["block_days"] == 7
    assert store.created_kw["start_date"] == date(2026, 6, 2)
    assert session.committed and runner.retrospective_called
    assert "retrospective" in view.results
    assert len(view.calendar) == 4  # ABAB


@pytest.mark.asyncio
async def test_create_rejects_non_controllable_pair(wire):
    wire(_StubStore())
    body = CreateExperimentRequest(
        lever_metric_id="vital.hrv_sdnn",  # both physiological → not_controllable
        outcome_metric_id="vital.resting_heart_rate",
    )
    with pytest.raises(HTTPException) as exc:
        await create_experiment(body=body, session=_Session())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_wrong_lever(wire):
    wire(_StubStore())
    # Pair is testable, but the user nominated the OUTCOME as the lever.
    body = CreateExperimentRequest(
        lever_metric_id="vital.resting_heart_rate",
        outcome_metric_id="activity.steps",
    )
    with pytest.raises(HTTPException) as exc:
        await create_experiment(body=body, session=_Session())
    assert exc.value.status_code == 422
    assert "lever" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_list_filters_by_status(wire):
    store = _StubStore(listing=[_experiment_row(), _experiment_row(status="completed")])
    wire(store)
    resp = await list_experiments(session=_Session(), status="collecting")
    assert resp.count == 2
    assert store.list_status == "collecting"


@pytest.mark.asyncio
async def test_list_rejects_unknown_status(wire):
    wire(_StubStore())
    with pytest.raises(HTTPException) as exc:
        await list_experiments(session=_Session(), status="bogus")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_detail_present_and_404(wire):
    wire(_StubStore(got=_experiment_row(), results={"controlled": _result_row()}))
    view = await get_experiment(experiment_id=EXP_ID, session=_Session())
    assert view.id == EXP_ID
    assert view.results["controlled"].adherence == {"status": "strong"}
    assert view.results["controlled"].n_a == 14

    wire(_StubStore(got=None))
    with pytest.raises(HTTPException) as exc:
        await get_experiment(experiment_id=EXP_ID, session=_Session())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_analyze_runs_controlled_and_404(wire):
    store = _StubStore(
        got=_experiment_row(status="completed"), results={"controlled": _result_row()}
    )
    runner = wire(store)
    view = await analyze_experiment(experiment_id=EXP_ID, session=_Session())
    assert runner.controlled_called and view.status == "completed"

    wire(_StubStore(got=None))
    with pytest.raises(HTTPException) as exc:
        await analyze_experiment(experiment_id=EXP_ID, session=_Session())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_abandon_sets_status_and_404(wire):
    store = _StubStore(set_result=_experiment_row(status="abandoned"))
    wire(store)
    session = _Session()
    view = await abandon_experiment(experiment_id=EXP_ID, session=session)
    assert view.status == "abandoned" and session.committed
    assert store.set_call == (EXP_ID, "abandoned")

    wire(_StubStore(set_result=None))
    with pytest.raises(HTTPException) as exc:
        await abandon_experiment(experiment_id=EXP_ID, session=_Session())
    assert exc.value.status_code == 404
