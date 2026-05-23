"""Pin source_id propagation through the aggregate-table writers.

Migration 009 added ``source_id`` to ``daily_activity`` and
``sleep_sessions``. This commit (P5-c.2) extends the writers to
populate it from each incoming sample's ``source`` field. These
tests use a recording AsyncSession to assert the SQL parameter
dict carries the right ``source_id`` value — no live DB required.

Three writer paths exercised:

  * ``_ingest_daily_quantity`` for metrics like ``step_count`` /
    ``distance_walking_running``.
  * ``_ingest_activity`` for ``activity_summaries`` payloads.
  * ``sleep_session_rows`` + ``_upsert_sleep_session`` for HealthKit-
    shaped sleep_analysis samples — source threads through the
    session aggregation step.

A separate test pins the contract that a sample without ``source``
lands with ``source_id = None`` (NULL in the DB), keeping the
'unknown' bucket compatibility the per-source reader relies on.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Importing through `server.ingestion.handlers` / .sleep (the canonical
# Phase 5E shims) avoids the partial-init cycle that hits when tests
# poke storage.timescale.measurements directly before server is ready.
from server.ingestion.handlers import (  # noqa: E402
    _ingest_activity,
    _ingest_daily_quantity,
    _ingest_metric,
    _ingest_workouts,
)
from server.ingestion.sleep import (  # noqa: E402
    _upsert_sleep_session,
    sleep_session_rows,
    sleep_stage_segments,
)

# ──────────────────────────────────────────────────────────────────────
# Recording session stub
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _Call:
    sql: str
    params: dict[str, Any]


@dataclass
class _RecordingSession:
    calls: list[_Call] = field(default_factory=list)
    next_returned_id: int = 1

    async def execute(self, statement, params=None) -> Any:
        sql = " ".join(str(statement).split())
        self.calls.append(_Call(sql=sql, params=dict(params or {})))
        return SimpleNamespace(
            scalar=lambda: self.next_returned_id, scalar_one_or_none=lambda: None
        )

    async def commit(self) -> None:  # pragma: no cover
        pass


def _params_for(session: _RecordingSession, *, sql_substring: str) -> list[dict[str, Any]]:
    return [c.params for c in session.calls if sql_substring in c.sql]


# ──────────────────────────────────────────────────────────────────────
# daily_activity — quantity path (step_count, distance_walking_running, …)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_quantity_writes_source_id_when_sample_carries_source():
    session = _RecordingSession()
    await _ingest_daily_quantity(
        session,
        device_id=42,
        metric="step_count",
        samples=[{"date": "2026-05-22", "qty": 8421, "source": "Apple Watch"}],
    )
    [params] = _params_for(session, sql_substring="INSERT INTO daily_activity")
    assert params["source_id"] == "Apple Watch"
    assert params["device_id"] == 42


@pytest.mark.asyncio
async def test_daily_quantity_writes_null_source_id_when_sample_has_no_source():
    """No ``source`` in the sample -> NULL in the DB. The per-source
    reader buckets NULL under ``slug == 'unknown'``.
    """
    session = _RecordingSession()
    await _ingest_daily_quantity(
        session,
        device_id=42,
        metric="step_count",
        samples=[{"date": "2026-05-22", "qty": 8421}],
    )
    [params] = _params_for(session, sql_substring="INSERT INTO daily_activity")
    assert params["source_id"] is None


@pytest.mark.asyncio
async def test_daily_quantity_accepts_sourceName_or_device_aliases():
    """HealthKit-shaped payloads use ``sourceName`` or ``device`` for
    the same identity. The writer normalises to ``source_id``.
    """
    for alias_key in ("sourceName", "device", "deviceName", "source_id"):
        session = _RecordingSession()
        await _ingest_daily_quantity(
            session,
            device_id=42,
            metric="step_count",
            samples=[{"date": "2026-05-22", "qty": 100, alias_key: "Whoop"}],
        )
        [params] = _params_for(session, sql_substring="INSERT INTO daily_activity")
        assert params["source_id"] == "Whoop", f"alias {alias_key!r} did not propagate"


# ──────────────────────────────────────────────────────────────────────
# daily_activity — activity_summaries path
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activity_summary_row_carries_source_id_when_sample_has_source():
    session = _RecordingSession()
    await _ingest_activity(
        session,
        device_id=42,
        samples=[
            {
                "date": "2026-05-22",
                "appleStandHours": 8,
                "source": "Apple Watch",
            }
        ],
    )
    [params] = _params_for(session, sql_substring="INSERT INTO daily_activity")
    assert params.get("source_id") == "Apple Watch"


# ──────────────────────────────────────────────────────────────────────
# sleep_sessions — sleep_session_rows + _upsert_sleep_session
# ──────────────────────────────────────────────────────────────────────


def test_sleep_session_rows_inherit_source_from_segments():
    """A single night of sleep is logged as N segments by the same
    watch; the aggregated session row inherits that source.
    """
    samples = [
        {
            "start": "2026-05-22T00:30:00Z",
            "end": "2026-05-22T02:00:00Z",
            "value": "deep",
            "source": "Apple Watch",
        },
        {
            "start": "2026-05-22T02:00:00Z",
            "end": "2026-05-22T05:30:00Z",
            "value": "core",
            "source": "Apple Watch",
        },
    ]
    rows = sleep_session_rows(device_id=42, samples=samples)
    assert len(rows) == 1
    assert rows[0]["source_id"] == "Apple Watch"


def test_sleep_session_picks_first_non_null_source_from_mixed_segments():
    """Defense against mixed-source segments — pick the first source
    that's present, ignore None entries. Should never happen in
    practice (one watch per night) but the picker is conservative.
    """
    samples = [
        {
            "start": "2026-05-22T00:30:00Z",
            "end": "2026-05-22T02:00:00Z",
            "value": "deep",
            # no source field — should be skipped
        },
        {
            "start": "2026-05-22T02:00:00Z",
            "end": "2026-05-22T05:30:00Z",
            "value": "core",
            "source": "Apple Watch",
        },
    ]
    rows = sleep_session_rows(device_id=42, samples=samples)
    assert len(rows) == 1
    assert rows[0]["source_id"] == "Apple Watch"


def test_sleep_session_source_id_is_none_when_no_segment_has_source():
    samples = [
        {
            "start": "2026-05-22T00:30:00Z",
            "end": "2026-05-22T02:00:00Z",
            "value": "deep",
        },
        {
            "start": "2026-05-22T02:00:00Z",
            "end": "2026-05-22T05:30:00Z",
            "value": "core",
        },
    ]
    rows = sleep_session_rows(device_id=42, samples=samples)
    assert rows[0]["source_id"] is None


def test_sleep_stage_segments_carry_source_alongside_stage_and_times():
    segments = sleep_stage_segments(
        [
            {
                "start": "2026-05-22T00:30:00Z",
                "end": "2026-05-22T02:00:00Z",
                "value": "deep",
                "source": "Apple Watch",
            }
        ]
    )
    assert segments == [
        {
            "start": segments[0]["start"],  # tz-aware datetime
            "end": segments[0]["end"],
            "stage": "deep",
            "source": "Apple Watch",
        }
    ]


@pytest.mark.asyncio
async def test_upsert_sleep_session_writes_source_id_into_sql_params():
    """The session-row dict is what the writer reads; this pins that
    source_id makes it through to the INSERT param bag.
    """
    session = _RecordingSession()
    row = {
        "device_id": 42,
        "start": "2026-05-22T00:30:00Z",
        "end": "2026-05-22T08:00:00Z",
        "total": 27_000_000,
        "deep": 5_000_000,
        "rem": 10_000_000,
        "light": 12_000_000,
        "awake": 0,
        "rr": None,
        "source_id": "Whoop",
    }
    await _upsert_sleep_session(session, row)
    [params] = _params_for(session, sql_substring="INSERT INTO sleep_sessions")
    assert params["source_id"] == "Whoop"


@pytest.mark.asyncio
async def test_upsert_sleep_session_writes_null_source_id_when_absent():
    """Defense in depth: even if a caller forgets to populate
    source_id in the row, the writer's setdefault sees None and the
    SQL still binds source_id = NULL — never a KeyError.
    """
    session = _RecordingSession()
    row = {
        "device_id": 42,
        "start": "2026-05-22T00:30:00Z",
        "end": "2026-05-22T08:00:00Z",
        "total": 27_000_000,
        "deep": 5_000_000,
        "rem": 10_000_000,
        "light": 12_000_000,
        "awake": 0,
        "rr": None,
    }
    await _upsert_sleep_session(session, row)
    [params] = _params_for(session, sql_substring="INSERT INTO sleep_sessions")
    assert params["source_id"] is None


# ──────────────────────────────────────────────────────────────────────
# dedicated metric tables — Whoop SpO2 / temperature + workouts
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedicated_blood_oxygen_writes_source_id_when_sample_has_source():
    session = _RecordingSession()
    await _ingest_metric(
        session,
        device_id=42,
        metric="blood_oxygen",
        samples=[{"date": "2026-05-22T08:00:00Z", "qty": 97.2, "source": "Whoop"}],
    )

    [params] = _params_for(session, sql_substring="INSERT INTO blood_oxygen")
    assert params["source_id"] == "Whoop"


@pytest.mark.asyncio
async def test_dedicated_body_temperature_writes_source_id_when_sample_has_source():
    session = _RecordingSession()
    await _ingest_metric(
        session,
        device_id=42,
        metric="body_temperature",
        samples=[{"date": "2026-05-22T08:00:00Z", "qty": 35.2, "source": "Whoop"}],
    )

    [params] = _params_for(session, sql_substring="INSERT INTO body_temperature")
    assert params["source_id"] == "Whoop"


@pytest.mark.asyncio
async def test_workout_writer_writes_source_id_when_sample_has_source():
    session = _RecordingSession()
    await _ingest_workouts(
        session,
        device_id=42,
        samples=[
            {
                "name": "Running",
                "start": "2026-05-22T18:00:00Z",
                "end": "2026-05-22T18:45:00Z",
                "source": "Whoop",
            }
        ],
    )

    [params] = _params_for(session, sql_substring="INSERT INTO workouts")
    assert params["source_id"] == "Whoop"
