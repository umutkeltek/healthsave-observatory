from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from storage.timescale.moments import TimescaleMomentsRepository


class _Result:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row = row
        self._rows = [] if rows is None else list(rows)
        self.rowcount = rowcount or (1 if row is not None else len(self._rows))

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Session:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return self.result


def _row(**over):
    return SimpleNamespace(
        id=over.get("id", 1),
        owner_id=over.get("owner_id", "00000000-0000-0000-0000-000000000001"),
        kind=over.get("kind", "illness"),
        grade=over.get("grade", "moderate"),
        title=over.get("title", "Mild cold"),
        note=over.get("note", "Started Monday evening"),
        start_at=over.get("start_at", datetime(2026, 7, 20, 18, tzinfo=UTC)),
        end_at=over.get("end_at", datetime(2026, 7, 22, 12, tzinfo=UTC)),
        created_at=None,
        updated_at=None,
    )


async def test_list_returns_typed_moments_descending() -> None:
    session = _Session(_Result(rows=[_row(id=2), _row(id=1)]))
    moments = await TimescaleMomentsRepository().list(session)
    assert [moment.id for moment in moments] == [2, 1]
    assert moments[0].kind == "illness"
    assert "ORDER BY start_at DESC" in session.calls[0][0]


async def test_create_inserts_and_returns_typed_moment() -> None:
    session = _Session(_Result(row=_row()))
    moment = await TimescaleMomentsRepository().create(
        session,
        kind="travel",
        title="Weekend in London",
        start_at=datetime(2026, 7, 25, 8, tzinfo=UTC),
        grade="mild",
    )
    assert moment.kind == "illness"
    sql, params = session.calls[0]
    assert "INSERT INTO moments" in sql
    assert params["kind"] == "travel"
    assert params["grade"] == "mild"


async def test_update_returns_none_for_wrong_owner() -> None:
    session = _Session(_Result(row=None, rowcount=0))
    result = await TimescaleMomentsRepository().update(
        session,
        id=99,
        kind="illness",
        title="Nonexistent",
        start_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert result is None


async def test_delete_returns_false_when_owner_mismatch() -> None:
    session = _Session(_Result(rowcount=0))
    assert await TimescaleMomentsRepository().delete(session, id=99) is False
