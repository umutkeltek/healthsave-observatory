"""Storage-result truth for HealthSave sync receipts."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import through the canonical shim to avoid the measurements/server partial-init cycle.
from server.ingestion.handlers import _ingest_metric  # noqa: E402


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar(self):
        return 1


class _BreakdownSession:
    def __init__(self, insert_flags: list[bool]):
        self.insert_flags = insert_flags
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "INSERT INTO heart_rate" in sql:
            assert "RETURNING" in sql
            return _Result({"inserted_new": self.insert_flags.pop(0)})
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

    assert result.accepted == 2
    assert result.inserted_new == 1
    assert result.deduped_existing == 1
    assert result.storage_result_level == "inserted_vs_existing"
