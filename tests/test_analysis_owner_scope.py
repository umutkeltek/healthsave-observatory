"""The primary person's analysis never absorbs another owner's samples.

Once participant keys write rows under other owner_ids, every raw-table
reader the statistical engine uses must filter by owner, and the
``hr_hourly`` continuous aggregate (grouped by bucket + device only, over a
global ``devices`` table) may only be read while it holds one owner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID
from storage.timescale import analysis

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)
PARTICIPANT = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def all(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Session:
    """``single_owner`` answers the guard; other queries get canned rows."""

    def __init__(self, *, single_owner: bool, hourly=(), raw=()):
        self.single_owner = single_owner
        self.hourly = list(hourly)
        self.raw = list(raw)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "AS single_owner" in sql:
            return _Result([SimpleNamespace(single_owner=self.single_owner)])
        if "FROM hr_hourly" in sql:
            return _Result(self.hourly)
        return _Result(self.raw)


def _sql(session: _Session) -> list[str]:
    return [sql for sql, _ in session.calls]


async def test_single_owner_install_keeps_reading_the_hourly_aggregate() -> None:
    session = _Session(single_owner=True, hourly=[SimpleNamespace(bucket=START, value=61.0)])
    points = await analysis.fetch_hr_observations(session, START, END)
    assert points == [(START, 61.0)]
    assert any("FROM hr_hourly" in sql for sql in _sql(session))
    assert not any("FROM heart_rate WHERE time" in sql for sql in _sql(session))


async def test_mixed_owner_install_reads_owner_filtered_raw_rows() -> None:
    session = _Session(
        single_owner=False,
        hourly=[SimpleNamespace(bucket=START, value=99.0)],
        raw=[SimpleNamespace(bucket=START, value=58.0)],
    )
    points = await analysis.fetch_hr_observations(session, START, END)
    assert points == [(START, 58.0)]
    assert not any("FROM hr_hourly" in sql for sql in _sql(session))
    raw_sql, raw_params = session.calls[-1]
    assert "owner_id = CAST(:owner_id AS UUID)" in raw_sql
    assert raw_params["owner_id"] == str(DEFAULT_OWNER_ID)


async def test_guard_probes_both_sides_of_the_owner_index() -> None:
    session = _Session(single_owner=True)
    await analysis.fetch_hr_observations(session, START, END, owner_id=PARTICIPANT)
    guard_sql, guard_params = session.calls[0]
    assert "owner_id < CAST(:owner_id AS UUID)" in guard_sql
    assert "owner_id > CAST(:owner_id AS UUID)" in guard_sql
    assert guard_params == {"owner_id": str(PARTICIPANT)}


async def test_daily_heart_rate_from_hourly_is_empty_once_owners_mix() -> None:
    session = _Session(single_owner=False, hourly=[SimpleNamespace(day=START, value=99.0)])
    assert await analysis.fetch_heart_rate_daily_from_hourly(session, START, END) == []
    assert not any("FROM hr_hourly" in sql for sql in _sql(session))


async def test_daily_heart_rate_from_hourly_unchanged_for_one_owner() -> None:
    rows = [SimpleNamespace(day=START, value=60.0, sample_count=24)]
    session = _Session(single_owner=True, hourly=rows)
    assert await analysis.fetch_heart_rate_daily_from_hourly(session, START, END) == rows


async def test_every_raw_reader_filters_by_owner() -> None:
    readers = (
        analysis.fetch_hrv_observations,
        analysis.fetch_workouts,
        analysis.fetch_heart_rate_daily_from_raw,
        analysis.fetch_hrv_daily,
    )
    for reader in readers:
        session = _Session(single_owner=True)
        await reader(session, START, END, owner_id=PARTICIPANT)
        sql, params = session.calls[-1]
        assert "owner_id = CAST(:owner_id AS UUID)" in sql, reader.__name__
        assert params["owner_id"] == str(PARTICIPANT), reader.__name__

        default_session = _Session(single_owner=True)
        await reader(default_session, START, END)
        assert default_session.calls[-1][1]["owner_id"] == str(DEFAULT_OWNER_ID)
