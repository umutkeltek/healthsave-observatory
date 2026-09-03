"""Storage writer: identity-aware source_uuid routing on Apple HealthKit dedicated tables.

Plan: 2026-09-03-v2-apple-ingest-wire.md, Slice 1.

Pins two behaviors on `_ingest_metric` for the dedicated Apple HealthKit
tables (``heart_rate`` etc.):

  * Legacy v1 wire (no ``uuid`` field on a sample) keeps using the original
    ``(time, device_id, owner_id)`` conflict clause so shipped clients are
    bit-for-bit unaffected by Slice 1.
  * v1 wire samples that DO carry ``uuid`` (forward-compatible: legacy clients
    that pick up the v2 server before the v2 iOS client lands) stamp
    ``source_uuid`` on the row and route through ``(owner_id, source_uuid)``
    ON CONFLICT — the new partial unique index added by migration 025.

Both paths land in a single batched INSERT per row set (PERFORMANCE-001
invariant from ``measurements.py::_execute_batch_insert_with_flags``).

This test sits next to ``tests/test_storage_insert_breakdown.py`` which
already pins the legacy batched-INSERT path; together they pin both arms
of the two-arm writer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import through the canonical shim to avoid the measurements/server
# partial-init cycle (same pattern as test_storage_insert_breakdown).
from server.ingestion.handlers import _ingest_metric  # noqa: E402


class _Result:
    """Fake SQLAlchemy result supporting batched ``INSERT ... RETURNING``."""

    def __init__(self, rows: list[dict] | None = None):
        self.rows = list(rows or [])
        self.cursor = 0

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        if self.cursor >= len(self.rows):
            return None
        row = self.rows[self.cursor]
        self.cursor += 1
        return row

    def scalar(self):
        return 1


class _RecordingSession:
    """Captures every SQL statement issued by the writer.

    Counts rows per INSERT by inspecting the positional ``:bpm_<n>`` bind
    keys the writer emits (the writer reuses column names as bind keys
    with a row suffix). One ``inserted_new`` flag per row across every
    INSERT in the call.
    """

    def __init__(self, insert_flags: list[bool]):
        self.calls: list[tuple[str, dict]] = []
        self.insert_flags = list(insert_flags)

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "INSERT INTO" in sql:
            # Discover row count from the highest positional bind suffix.
            rows_in_this_insert = 1
            for key in (params or {}):
                for suffix in key.split("_"):
                    if suffix.isdigit():
                        rows_in_this_insert = max(
                            rows_in_this_insert, int(suffix) + 1
                        )
                        break
            rows = [
                {"inserted_new": bool(self.insert_flags.pop(0))}
                for _ in range(rows_in_this_insert)
            ]
            return _Result(rows)
        return _Result()


@pytest.mark.asyncio
async def test_legacy_samples_use_time_device_owner_conflict():
    """Samples without uuid: keep the (time, device_id, owner_id) conflict."""
    session = _RecordingSession(insert_flags=[True, True])

    result = await _ingest_metric(
        session,
        device_id=42,
        metric="heart_rate",
        samples=[
            {"date": "2026-05-28T10:00:00Z", "qty": 72, "source": "Apple Watch"},
            {"date": "2026-05-28T10:01:00Z", "qty": 73, "source": "Apple Watch"},
        ],
    )

    insert_calls = [c for c in session.calls if "INSERT INTO heart_rate" in c[0]]
    assert len(insert_calls) == 1, (
        f"expected single batched INSERT for legacy arm, got {len(insert_calls)}"
    )
    sql = insert_calls[0][0]
    assert "ON CONFLICT (time, device_id, owner_id)" in sql, (
        f"legacy arm must conflict on (time, device_id, owner_id); got: {sql}"
    )
    assert "source_uuid" not in sql, (
        "legacy arm must not address source_uuid in ON CONFLICT"
    )
    assert result.accepted == 2
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_uuid_bearing_samples_use_identity_conflict():
    """Samples with uuid: route through (owner_id, source_uuid) ON CONFLICT."""
    session = _RecordingSession(insert_flags=[True])

    result = await _ingest_metric(
        session,
        device_id=42,
        metric="heart_rate",
        samples=[
            {
                "date": "2026-05-28T10:00:00Z",
                "qty": 72,
                "source": "Apple Watch",
                "uuid": "d2c70000-0000-4000-8000-000000000001",
            },
        ],
    )

    insert_calls = [c for c in session.calls if "INSERT INTO heart_rate" in c[0]]
    assert len(insert_calls) == 1, (
        f"expected single batched INSERT for identity arm, got {len(insert_calls)}"
    )
    sql = insert_calls[0][0]
    assert "ON CONFLICT (owner_id, source_uuid)" in sql, (
        f"identity arm must conflict on (owner_id, source_uuid); got: {sql}"
    )
    params = insert_calls[0][1]
    assert any(
        v == "d2c70000-0000-4000-8000-000000000001" for v in params.values()
    ), f"expected source_uuid in bind params; got keys: {sorted(params.keys())}"
    assert result.accepted == 1
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_mixed_batch_splits_into_two_inserts():
    """A single batch with both kinds of samples uses both arms (two INSERTs).

    One INSERT for the identity arm, one for the legacy arm. Total accepted
    counts both rows; no row is silently dropped because the routing split
    is exhaustive.
    """
    # Two samples → two rows → two insert flags.
    session = _RecordingSession(insert_flags=[True, True])

    result = await _ingest_metric(
        session,
        device_id=42,
        metric="heart_rate",
        samples=[
            {
                "date": "2026-05-28T10:00:00Z",
                "qty": 72,
                "source": "Apple Watch",
                "uuid": "d2c70000-0000-4000-8000-000000000002",
            },
            {
                "date": "2026-05-28T10:01:00Z",
                "qty": 73,
                "source": "Apple Watch",
            },
        ],
    )

    insert_calls = [c for c in session.calls if "INSERT INTO heart_rate" in c[0]]
    assert len(insert_calls) == 2, (
        f"expected two INSERTs (one per arm), got {len(insert_calls)}: "
        f"{[c[0][:80] for c in insert_calls]}"
    )
    sqls = [c[0] for c in insert_calls]
    assert any("ON CONFLICT (owner_id, source_uuid)" in s for s in sqls), (
        "identity arm must appear in mixed batch"
    )
    assert any("ON CONFLICT (time, device_id, owner_id)" in s for s in sqls), (
        "legacy arm must appear in mixed batch"
    )
    assert result.accepted == 2
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_step_count_ignores_uuid():
    """``step_count`` is in ``DAILY_ACTIVITY_QUANTITY_FIELDS``, not
    ``DEDICATED_TABLES``. Slice 1's source_uuid change does NOT touch the
    daily_activity writer; uuid on a daily-quantity sample is silently
    ignored. We use distinct ``date`` values to avoid the same-day dedup
    collapse so the assertion stays meaningful.
    """
    session = _RecordingSession(insert_flags=[True, True])

    result = await _ingest_metric(
        session,
        device_id=42,
        metric="step_count",
        samples=[
            {"date": "2026-05-28", "qty": 100, "source": "iPhone"},
            {
                "date": "2026-05-29",
                "qty": 200,
                "source": "iPhone",
                "uuid": "d2c70000-0000-4000-8000-000000000003",
            },
        ],
    )

    assert result.accepted == 2, (
        f"both samples on distinct dates must be accepted; got: {result}"
    )
    insert_calls = [c for c in session.calls if "INSERT INTO" in c[0]]
    assert insert_calls, "expected at least one INSERT for step_count"
    for sql, _ in insert_calls:
        assert "source_uuid" not in sql, (
            f"step_count writes to daily_activity; source_uuid must not "
            f"appear in its INSERT: {sql[:200]}"
        )