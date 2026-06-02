"""Tests for TimescaleExperimentRepository.

FakeSession discipline — no live DB. Each repository method runs exactly one
``execute``; the fake returns queued rows and records the (normalized SQL,
params) so we can assert both the row mapping and the query shape.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from storage.timescale.experiments import (
    ExperimentResultRow,
    ExperimentRow,
    TimescaleExperimentRepository,
)

SENTINEL = "00000000-0000-0000-0000-000000000001"
EXP_ID = UUID("11111111-1111-1111-1111-111111111111")


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Session:
    """Returns one queued row-list per ``execute`` call, in order."""

    def __init__(self, queue):
        self._queue = list(queue)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        rows = self._queue.pop(0) if self._queue else []
        return _Result(rows)


def _exp_row(**overrides):
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
    return SimpleNamespace(**base)


def _result_row(**overrides):
    base = dict(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        experiment_id=EXP_ID,
        kind="controlled",
        computed_at=datetime(2026, 7, 1, tzinfo=UTC),
        direction="decrease",
        diff=-3.2,
        effect_size=-0.7,
        p_value=0.08,
        inference="randomization_test",
        summary="resting heart rate was 3.2 lower during intervention blocks",
        structured_data={"n_a": 14, "n_b": 14},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def repo():
    return TimescaleExperimentRepository()


@pytest.mark.asyncio
async def test_create_experiment_inserts_and_maps(repo):
    session = _Session([[_exp_row()]])
    row = await repo.create_experiment(
        session,
        lever_metric_id="activity.steps",
        outcome_metric_id="vital.resting_heart_rate",
        design="ABAB",
        block_days=7,
        start_date=date(2026, 6, 2),
        hypothesis="More steps lower my RHR",
    )
    assert isinstance(row, ExperimentRow)
    assert row.id == EXP_ID and row.lever_metric_id == "activity.steps"
    assert row.status == "collecting"

    sql, params = session.calls[0]
    assert sql.startswith("INSERT INTO experiments")
    assert "RETURNING" in sql
    assert params["owner_id"] == SENTINEL and params["workspace_id"] == SENTINEL
    assert params["design"] == "ABAB" and params["block_days"] == 7


@pytest.mark.asyncio
async def test_get_experiment_present_and_absent(repo):
    present = _Session([[_exp_row()]])
    got = await repo.get_experiment(present, experiment_id=EXP_ID)
    assert got is not None and got.id == EXP_ID

    absent = _Session([[]])
    assert await repo.get_experiment(absent, experiment_id=EXP_ID) is None


@pytest.mark.asyncio
async def test_list_experiments_status_filter(repo):
    session = _Session([[_exp_row(), _exp_row(status="completed")]])
    rows = await repo.list_experiments(session, status="collecting")
    assert len(rows) == 2 and all(isinstance(r, ExperimentRow) for r in rows)

    sql, params = session.calls[0]
    assert "status = :status" in sql and params["status"] == "collecting"

    # No status → no status clause/param.
    session2 = _Session([[_exp_row()]])
    await repo.list_experiments(session2)
    sql2, params2 = session2.calls[0]
    assert "status = :status" not in sql2 and "status" not in params2


@pytest.mark.asyncio
async def test_set_status_returns_row_or_none(repo):
    session = _Session([[_exp_row(status="abandoned")]])
    row = await repo.set_status(session, experiment_id=EXP_ID, status="abandoned")
    assert row is not None and row.status == "abandoned"
    sql, params = session.calls[0]
    assert sql.startswith("UPDATE experiments") and params["status"] == "abandoned"

    missing = _Session([[]])
    assert await repo.set_status(missing, experiment_id=EXP_ID, status="completed") is None


@pytest.mark.asyncio
async def test_insert_result_serializes_json_and_maps(repo):
    session = _Session([[_result_row()]])
    row = await repo.insert_result(
        session,
        experiment_id=EXP_ID,
        kind="controlled",
        direction="decrease",
        diff=-3.2,
        effect_size=-0.7,
        p_value=0.08,
        inference="randomization_test",
        summary="resting heart rate was 3.2 lower during intervention blocks",
        structured_data={"n_a": 14, "n_b": 14},
    )
    assert isinstance(row, ExperimentResultRow)
    assert row.structured_data == {"n_a": 14, "n_b": 14}
    assert row.kind == "controlled" and row.p_value == 0.08

    sql, params = session.calls[0]
    assert sql.startswith("INSERT INTO experiment_results")
    # structured_data is serialized to a JSON string for the JSONB cast.
    assert isinstance(params["structured_data"], str)
    assert '"n_a": 14' in params["structured_data"]


@pytest.mark.asyncio
async def test_insert_result_parses_json_string_payload(repo):
    # asyncpg returns JSONB as a dict, but a str must still decode cleanly.
    session = _Session([[_result_row(structured_data='{"n_a": 7, "n_b": 7}')]])
    row = await repo.insert_result(
        session,
        experiment_id=EXP_ID,
        kind="retrospective",
        direction="flat",
        diff=0.0,
        effect_size=0.0,
        p_value=None,
        inference="observational",
        summary="about the same",
        structured_data={},
    )
    assert row.structured_data == {"n_a": 7, "n_b": 7}


@pytest.mark.asyncio
async def test_latest_results_by_kind_maps_dict(repo):
    session = _Session([[_result_row(kind="controlled"), _result_row(kind="retrospective")]])
    results = await repo.latest_results_by_kind(session, experiment_id=EXP_ID)
    assert set(results) == {"controlled", "retrospective"}
    assert all(isinstance(r, ExperimentResultRow) for r in results.values())
    sql, _ = session.calls[0]
    assert "DISTINCT ON (kind)" in sql
