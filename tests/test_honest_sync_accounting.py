"""Honest sync accounting (provably-perfect-sync, Phase 1).

Regression guard for the "~95% of my sleep was rejected" lie: ``records_skipped``
/ ``records_rejected`` used to be derived as ``received - accepted``, which
conflated three unrelated things — aggregation rollup (sleep stages folded into
sessions, preserved in ``sleep_stages``), legitimate in-batch duplicate collapse
(HealthKit full-export overlap), and genuine validation failure. Only the last
is a rejection. These tests pin that distinction at the writer boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Canonical shim import avoids the measurements/server partial-init cycle.
from server.ingestion.handlers import _ingest_metric  # noqa: E402


class _Result:
    def __init__(self, row=None, scalar_value=1):
        self.row = row
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar(self):
        return self.scalar_value


class _FakeSession:
    """Minimal session double: an ``inserted_new`` row for dedicated-metric
    upserts (``RETURNING (xmax = 0)``) and a scalar id for sleep sessions."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "RETURNING (xmax = 0)" in sql:
            return _Result({"inserted_new": True})
        return _Result(scalar_value=1)


@pytest.mark.asyncio
async def test_sleep_aggregation_is_not_reported_as_rejected():
    """N raw stage segments roll up into M sessions; the stages are preserved
    in ``sleep_stages``, so ``rejected`` MUST be 0 — not N-M (the old lie)."""
    session = _FakeSession()
    samples = [
        {
            "startDate": "2026-05-28T23:00:00Z",
            "endDate": "2026-05-28T23:40:00Z",
            "value": "core",
            "source": "Apple Watch",
        },
        {
            "startDate": "2026-05-28T23:40:00Z",
            "endDate": "2026-05-29T00:50:00Z",
            "value": "deep",
            "source": "Apple Watch",
        },
        {
            "startDate": "2026-05-29T00:50:00Z",
            "endDate": "2026-05-29T01:30:00Z",
            "value": "rem",
            "source": "Apple Watch",
        },
        {
            "startDate": "2026-05-29T01:30:00Z",
            "endDate": "2026-05-29T06:00:00Z",
            "value": "core",
            "source": "Apple Watch",
        },
    ]

    result = await _ingest_metric(session, device_id=7, metric="sleep_analysis", samples=samples)

    # 4 contiguous stage segments collapse into a single session.
    assert int(result.accepted) == 1
    assert result.rejected == 0  # old code would have reported 3 "skipped"


@pytest.mark.asyncio
async def test_in_batch_duplicate_is_deduped_not_rejected():
    """Two samples sharing (time, device, owner) are legitimate HealthKit
    full-export overlap — counted as ``deduped_in_batch``, never rejected."""
    session = _FakeSession()
    samples = [
        {"date": "2026-05-22T08:00:00Z", "qty": 61, "source": "Apple Watch"},
        {"date": "2026-05-22T08:00:00Z", "qty": 62, "source": "Apple Watch"},
    ]

    result = await _ingest_metric(session, device_id=42, metric="heart_rate", samples=samples)

    assert result.accepted == 1
    assert result.rejected == 0
    assert result.deduped_in_batch == 1


@pytest.mark.asyncio
async def test_genuinely_invalid_samples_are_counted_as_rejected():
    """Samples missing time/value ARE true rejections and must be counted."""
    session = _FakeSession()
    samples = [
        {"qty": 61, "source": "Apple Watch"},  # missing date
        {"date": "2026-05-22T08:00:00Z", "source": "x"},  # missing qty
        {"date": "2026-05-22T08:05:00Z", "qty": 63, "source": "Apple Watch"},  # valid
    ]

    result = await _ingest_metric(session, device_id=42, metric="heart_rate", samples=samples)

    assert result.accepted == 1
    assert result.rejected == 2
    assert result.deduped_in_batch == 0


@pytest.mark.asyncio
async def test_generic_metric_in_batch_duplicate_is_deduped_not_rejected():
    """CardinalityViolation regression (2026-07-28): the catch-all
    ``quantity_samples`` path batches N rows into ONE upsert, and Postgres
    rejects the statement if two rows share the conflict key. Same-timestamp
    duplicates are legitimate HealthKit overlap — they must collapse before
    the insert and count as ``deduped_in_batch``, never crash the batch."""
    session = _FakeSession()
    samples = [
        {"date": "2026-07-28T08:00:00Z", "qty": 14.5, "source": "Apple Watch"},
        {"date": "2026-07-28T08:00:00Z", "qty": 14.8, "source": "Apple Watch"},
        {"date": "2026-07-28T08:01:00Z", "qty": 15.1, "source": "Apple Watch"},
    ]

    result = await _ingest_metric(session, device_id=42, metric="respiratory_rate", samples=samples)

    assert result.accepted == 2
    assert result.rejected == 0
    assert result.deduped_in_batch == 1

    # Structural guard: the bound rows sent to quantity_samples carry unique
    # conflict keys — the property whose violation 422'd every live batch.
    batch_calls = [
        (sql, params) for sql, params in session.calls if "INSERT INTO quantity_samples" in sql
    ]
    assert batch_calls, "expected a quantity_samples upsert"
    sql, params = batch_calls[0]
    bound_times = [v for k, v in params.items() if k == "time" or k.startswith("time_")]
    assert len(bound_times) == len(set(bound_times)) == 2


def test_dedupe_helper_merge_non_null_folds_later_values_per_column():
    """COALESCE-style update sets (daily_activity) need column-wise merge:
    later non-None values win, earlier values survive a later None."""
    from storage.timescale.measurements import _dedupe_rows_for_upsert

    rows = [
        {"date": "2026-07-28", "device_id": 1, "owner_id": "o", "steps": 100, "source_id": "a"},
        {"date": "2026-07-28", "device_id": 1, "owner_id": "o", "steps": 250, "source_id": None},
    ]

    deduped, count = _dedupe_rows_for_upsert(
        rows, ["date", "device_id", "owner_id"], "activity_summaries", merge_non_null=True
    )

    assert count == 1
    assert len(deduped) == 1
    assert deduped[0]["steps"] == 250
    assert deduped[0]["source_id"] == "a"
