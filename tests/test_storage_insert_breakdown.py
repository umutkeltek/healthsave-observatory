"""Storage-result truth for HealthSave sync receipts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import through the canonical shim to avoid the measurements/server partial-init cycle.
from server.ingestion.handlers import _ingest_metric  # noqa: E402


class _Result:
    """Fake SQLAlchemy result supporting batched ``INSERT ... RETURNING``.

    ``mappings()`` returns a row list. The current implementation of
    ``_execute_batch_insert_with_flags`` accepts either a real
    ``MappingResult.all()`` (production asyncpg) or a sequence of
    ``.first()`` calls (this mock).
    """

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


class _BreakdownSession:
    def __init__(self, insert_flags: list[bool]):
        self.insert_flags = list(insert_flags)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "INSERT INTO heart_rate" in sql:
            assert "RETURNING" in sql
            # PERFORMANCE-001: one batched execute for the whole batch.
            # Real asyncpg returns one row per VALUES tuple; the helper reads
            # them in order and treats each ``inserted_new`` flag as that
            # tuple's outcome.
            rows = [
                {"inserted_new": bool(self.insert_flags.pop(0))}
                for _ in range(len(self.insert_flags))
            ]
            return _Result(rows)
        return _Result()


@pytest.mark.asyncio
async def test_dedicated_metric_result_splits_inserted_new_from_existing_rows():
    session = _BreakdownSession(insert_flags=[True, False])

    result = await _ingest_metric(
        session,
        device_id=42,
        metric="heart_rate",
        samples=[
            {"date": "2026-05-28T10:00:00Z", "qty": 72, "source": "Apple Watch"},
            {"date": "2026-05-28T10:01:00Z", "qty": 73, "source": "Apple Watch"},
        ],
    )

    # PERFORMANCE-001: a single execute call carries the entire batch.
    insert_calls = [c for c in session.calls if "INSERT INTO heart_rate" in c[0]]
    assert len(insert_calls) == 1, f"expected single batched INSERT, got {len(insert_calls)}"

    assert result.accepted == 2
    assert result.inserted_new == 1
    assert result.deduped_existing == 1
    assert result.storage_result_level == "inserted_vs_existing"


@pytest.mark.asyncio
async def test_batched_upsert_does_one_round_trip_per_metric():
    """PERFORMANCE-001 contract: one session.execute per ingest metric, not one per row."""
    session = _BreakdownSession(insert_flags=[True] * 50)

    samples = [
        {"date": f"2026-05-28T10:{i // 60:02d}:{i % 60:02d}Z", "qty": 70 + i, "source": "Apple Watch"}
        for i in range(50)
    ]

    result = await _ingest_metric(session, device_id=42, metric="heart_rate", samples=samples)

    insert_calls = [c for c in session.calls if "INSERT INTO heart_rate" in c[0]]
    assert len(insert_calls) == 1
    # 50 samples accepted as 50 inserted_new.
    assert result.accepted == 50
    assert result.inserted_new == 50
