"""Tests for the Timescale export repository.

FakeSession discipline — no live DB. We assert the whitelist-driven SQL shape,
bound parameter behavior, and the CSV/JSON/list surfaces the v2 route relies
on.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.timescale.export import (  # noqa: E402
    MAX_ROW_LIMIT,
    METRIC_EXPORTS,
    TimescaleExportRepository,
)


class _Row(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row (attribute access)."""


class _Result:
    def __init__(self, rows=None, first_row=None):
        self._rows = list(rows or [])
        self._first_row = first_row

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._first_row


class _QueueSession:
    """Async session whose successive ``execute`` calls return queued results."""

    def __init__(self, results):
        self._queue = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return self._queue.pop(0) if self._queue else _Result([])


@pytest.mark.asyncio
async def test_export_metric_rows_builds_whitelisted_heart_rate_query():
    repo = TimescaleExportRepository()
    row = (datetime(2026, 5, 1, 12, 0, tzinfo=UTC), 62, "resting", "watch")
    session = _QueueSession([_Result(rows=[row])])

    columns, rows = await repo.export_metric_rows(session, metric="heart_rate")

    assert columns == ["time", "bpm", "context", "source_id"]
    assert rows == [row]
    sql, params = session.calls[0]
    assert "FROM heart_rate" in sql
    assert "owner_id = :owner_id" in sql
    assert "ORDER BY time DESC" in sql
    assert "LIMIT :limit" in sql
    assert params["limit"] > 0


@pytest.mark.asyncio
async def test_workouts_export_never_references_legacy_altitude_gain():
    repo = TimescaleExportRepository()
    session = _QueueSession([_Result(rows=[])])

    await repo.export_metric_rows(session, metric="workouts")

    sql, _ = session.calls[0]
    assert "FROM workouts" in sql
    assert "altitude_gain_m" not in sql


@pytest.mark.asyncio
async def test_unknown_metric_raises_key_error():
    repo = TimescaleExportRepository()

    with pytest.raises(KeyError):
        await repo.export_metric_rows(_QueueSession([]), metric="not_real")


@pytest.mark.asyncio
async def test_quantity_samples_submetric_binds_metric_filter():
    repo = TimescaleExportRepository()
    session = _QueueSession([_Result(rows=[])])

    await repo.export_metric_rows(session, metric="vo2_max")

    sql, params = session.calls[0]
    assert "FROM quantity_samples" in sql
    assert "metric_name = :metric_filter" in sql
    assert params["metric_filter"] == "vo2_max"


@pytest.mark.asyncio
async def test_date_binding_uses_date_for_daily_activity_and_datetime_for_timeseries():
    repo = TimescaleExportRepository()
    daily_session = _QueueSession([_Result(rows=[])])
    hr_session = _QueueSession([_Result(rows=[])])

    await repo.export_metric_rows(
        daily_session,
        metric="daily_activity",
        date_from=date(2026, 5, 1),
    )
    await repo.export_metric_rows(
        hr_session,
        metric="heart_rate",
        date_from=date(2026, 5, 1),
    )

    daily_params = daily_session.calls[0][1]
    hr_params = hr_session.calls[0][1]
    assert isinstance(daily_params["date_from"], date)
    assert not isinstance(daily_params["date_from"], datetime)
    assert isinstance(hr_params["date_from"], datetime)
    assert hr_params["date_from"].tzinfo is UTC


@pytest.mark.asyncio
async def test_limit_is_capped_at_max_row_limit():
    repo = TimescaleExportRepository()
    session = _QueueSession([_Result(rows=[])])

    await repo.export_metric_rows(session, metric="heart_rate", limit=999999)

    _, params = session.calls[0]
    assert params["limit"] == MAX_ROW_LIMIT


@pytest.mark.asyncio
async def test_export_metric_csv_includes_header_line():
    repo = TimescaleExportRepository()
    row = (datetime(2026, 5, 1, 12, 0, tzinfo=UTC), 62, "resting", "watch")
    session = _QueueSession([_Result(rows=[row])])

    csv_data = await repo.export_metric_csv(session, metric="heart_rate")

    assert csv_data.splitlines()[0] == "time,bpm,context,source_id"


@pytest.mark.asyncio
async def test_export_metric_json_serializes_datetimes_to_iso_strings():
    repo = TimescaleExportRepository()
    row = (datetime(2026, 5, 1, 12, 0, tzinfo=UTC), 62, "resting", "watch")
    session = _QueueSession([_Result(rows=[row])])

    payload = await repo.export_metric_json(session, metric="heart_rate")

    assert payload == [
        {
            "time": "2026-05-01T12:00:00+00:00",
            "bpm": 62,
            "context": "resting",
            "source_id": "watch",
        }
    ]


@pytest.mark.asyncio
async def test_list_available_metrics_returns_every_whitelisted_metric():
    repo = TimescaleExportRepository()
    stamp = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    results = [_Result(first_row=_Row(c=2, lo=stamp, hi=stamp)) for _ in METRIC_EXPORTS]
    session = _QueueSession(results)

    metrics = await repo.list_available_metrics(session)

    assert len(metrics) == len(METRIC_EXPORTS)
    by_metric = {entry["metric"]: entry for entry in metrics}
    assert by_metric["heart_rate"]["count"] == 2
    assert by_metric["heart_rate"]["oldest"] == "2026-05-01T12:00:00+00:00"
    assert by_metric["vo2_max"]["display_name"] == "VO2 Max"
