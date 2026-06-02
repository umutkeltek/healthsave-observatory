"""Tests for analysis.experiments.ExperimentRunner.

Composes a real pure-stats run with a fake session + monkeypatched storage
handles (``_sql`` / ``_experiments``) — no DB, no SQL. Verifies that the runner
windows the series, picks the right analysis per kind, persists the right
result, and completes the experiment when its window has elapsed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import analysis.experiments as runner_mod
import pytest
from analysis.experiments import ExperimentRunner

EXP_ID = UUID("11111111-1111-1111-1111-111111111111")
START = date(2026, 1, 1)


class _FakeSession:
    def __init__(self):
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.committed = True


def _factory(session):
    def make():
        return session

    return make


class _StubSql:
    """Returns canned daily-series rows per metric, ignoring the window bounds."""

    def __init__(self, series_by_metric: dict[str, dict[date, float]]):
        self.series_by_metric = series_by_metric

    async def fetch_metric_daily_series(self, session, metric_id, start, end):
        series = self.series_by_metric.get(metric_id, {})
        return [SimpleNamespace(day=day, value=value) for day, value in series.items()]


class _StubExperiments:
    def __init__(self):
        self.results: list[dict] = []
        self.status_calls: list[tuple] = []

    async def insert_result(self, session, **kw):
        self.results.append(kw)
        return SimpleNamespace(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            experiment_id=kw["experiment_id"],
            kind=kw["kind"],
            computed_at=datetime(2026, 7, 1, tzinfo=UTC),
            **{
                k: kw[k]
                for k in ("direction", "diff", "effect_size", "p_value", "inference", "summary")
            },
            structured_data=kw["structured_data"],
        )

    async def set_status(self, session, *, experiment_id, status, **kw):
        self.status_calls.append((experiment_id, status))
        return None


def _experiment(**overrides):
    base = dict(
        id=EXP_ID,
        lever_metric_id="activity.steps",
        outcome_metric_id="vital.resting_heart_rate",
        design="ABABAB",
        block_days=2,  # 6 blocks × 2 days = 12-day window
        start_date=START,
        status="collecting",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _phase_series(
    a_value: float, b_value: float, design: str, block_days: int
) -> dict[date, float]:
    """Constant-per-phase daily series over a calendar starting at START."""
    out: dict[date, float] = {}
    day = START
    for label in design:
        for _ in range(block_days):
            out[day] = a_value if label == "A" else b_value
            day = day + timedelta(days=1)
    return out


@pytest.fixture
def stubs(monkeypatch):
    experiments = _StubExperiments()

    def install(series_by_metric):
        sql = _StubSql(series_by_metric)
        monkeypatch.setattr(runner_mod, "_sql", lambda: sql)
        monkeypatch.setattr(runner_mod, "_experiments", lambda: experiments)
        return experiments

    return install


@pytest.mark.asyncio
async def test_run_controlled_completes_and_persists(stubs):
    outcome = _phase_series(50.0, 60.0, "ABABAB", 2)  # B higher → increase
    lever = _phase_series(10.0, 30.0, "ABABAB", 2)  # strong separation → adherence
    experiments = stubs({"vital.resting_heart_rate": outcome, "activity.steps": lever})

    session = _FakeSession()
    exp = _experiment()
    # as_of well past the 12-day window → complete.
    await ExperimentRunner(_factory(session)).run_controlled(exp, as_of=date(2026, 2, 1))

    assert session.committed
    assert len(experiments.results) == 1
    res = experiments.results[0]
    assert res["kind"] == "controlled"
    assert res["direction"] == "increase"
    assert res["inference"] == "randomization_test"
    assert res["structured_data"]["adherence"]["status"] == "strong"
    # Window elapsed + status collecting → completed.
    assert experiments.status_calls == [(EXP_ID, "completed")]


@pytest.mark.asyncio
async def test_run_controlled_midrun_does_not_complete(stubs):
    outcome = _phase_series(50.0, 60.0, "ABABAB", 2)
    lever = _phase_series(10.0, 30.0, "ABABAB", 2)
    experiments = stubs({"vital.resting_heart_rate": outcome, "activity.steps": lever})

    session = _FakeSession()
    exp = _experiment()
    # as_of inside the window (day 5 of 12) → not complete.
    await ExperimentRunner(_factory(session)).run_controlled(exp, as_of=date(2026, 1, 6))

    assert len(experiments.results) == 1
    assert experiments.status_calls == []  # still collecting


@pytest.mark.asyncio
async def test_run_retrospective_persists_observational(stubs):
    # lever rises across 10 days; outcome falls with it → observational decrease.
    lever = {START + timedelta(days=i): float(i) for i in range(10)}
    outcome = {START + timedelta(days=i): 100.0 - 2.0 * i for i in range(10)}
    experiments = stubs({"vital.resting_heart_rate": outcome, "activity.steps": lever})

    session = _FakeSession()
    result = await ExperimentRunner(_factory(session)).run_retrospective(
        _experiment(), as_of=date(2026, 1, 15)
    )

    assert result is not None and session.committed
    res = experiments.results[0]
    assert res["kind"] == "retrospective"
    assert res["inference"] == "observational"
    assert res["direction"] == "decrease"
    assert res["structured_data"]["method"] == "lever_median_split"


@pytest.mark.asyncio
async def test_run_retrospective_skips_when_insufficient(stubs):
    # Only 3 overlapping days → below the median-split floor → nothing persisted.
    lever = {START + timedelta(days=i): float(i) for i in range(3)}
    outcome = {START + timedelta(days=i): float(i) for i in range(3)}
    experiments = stubs({"vital.resting_heart_rate": outcome, "activity.steps": lever})

    session = _FakeSession()
    result = await ExperimentRunner(_factory(session)).run_retrospective(
        _experiment(), as_of=date(2026, 1, 15)
    )

    assert result is None
    assert experiments.results == []
