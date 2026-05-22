"""Tests for the per-source snapshot reader.

The reader is pure SQL + a small Python merge — tests inject a fake
``AsyncSession`` that returns canned per-metric rows. No DB needed.

Covered behaviours:

  * ``source_slug`` normalizes punctuation, whitespace, empties.
  * Each ``source_id`` that appears in HR or HRV becomes one
    :class:`SourceHealthSnapshot`.
  * Sources that appear in only one metric still emit a snapshot,
    with ``None`` for the missing one.
  * Rows with NULL / empty ``source_id`` get bucketed under
    ``slug == "unknown"`` rather than fragmenting into multiple empty
    sub-devices.
  * Output is sorted by slug so call sites + logs are deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "py"))

from homeassistant_mqtt.snapshot import (  # noqa: E402
    SourceHealthSnapshot,
    source_slug,
)
from storage.timescale.homeassistant import (  # noqa: E402
    TimescaleHealthSnapshotRepository,
)

# ─── source_slug ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Apple Watch", "apple_watch"),
        ("Umut's iPhone", "umut_s_iphone"),
        ("Whoop", "whoop"),
        ("HealthSave  (cycle avg)", "healthsave_cycle_avg"),
        ("APPLE WATCH", "apple_watch"),
        ("  trailing  ", "trailing"),
        ("___only_underscores___", "only_underscores"),
        ("123-numeric-456", "123_numeric_456"),
    ],
)
def test_source_slug_normalizes_to_topic_safe_id(raw: str, expected: str) -> None:
    assert source_slug(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "!!!", "____"])
def test_source_slug_falls_back_to_unknown_for_empty_input(raw) -> None:
    assert source_slug(raw) == "unknown"


def test_source_snapshot_slug_property_uses_source_slug() -> None:
    from datetime import UTC, datetime

    snap = SourceHealthSnapshot(
        collected_at=datetime(2026, 5, 22, tzinfo=UTC),
        source_id="Apple Watch",
        heart_rate=72,
        hrv_latest_ms=64.3,
    )
    assert snap.slug == "apple_watch"


# ─── fetch_snapshots_by_source ────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    """Returns canned rows based on a substring match in the SQL."""

    def __init__(self, *, hr_rows: list[tuple], hrv_rows: list[tuple]) -> None:
        self._hr = hr_rows
        self._hrv = hrv_rows
        self.executed_queries: list[str] = []

    async def execute(self, statement) -> _FakeResult:
        sql = str(statement)
        self.executed_queries.append(sql)
        if "FROM heart_rate" in sql:
            return _FakeResult(self._hr)
        if "FROM hrv" in sql:
            return _FakeResult(self._hrv)
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_fetch_snapshots_by_source_returns_one_per_source() -> None:
    session = _FakeSession(
        hr_rows=[("Apple Watch", 72), ("Whoop", 68)],
        hrv_rows=[("Apple Watch", 64.31), ("Whoop", 58.92)],
    )
    repo = TimescaleHealthSnapshotRepository()
    snapshots = await repo.fetch_snapshots_by_source(session)

    assert {s.slug for s in snapshots} == {"apple_watch", "whoop"}
    by_slug = {s.slug: s for s in snapshots}
    assert by_slug["apple_watch"].heart_rate == 72
    assert by_slug["apple_watch"].hrv_latest_ms == 64.3
    assert by_slug["whoop"].heart_rate == 68
    assert by_slug["whoop"].hrv_latest_ms == 58.9


@pytest.mark.asyncio
async def test_fetch_snapshots_by_source_handles_partial_data_per_source() -> None:
    """A source that reports only HR (not HRV) still gets a snapshot —
    with hrv_latest_ms=None. Mirrors reality: an iPhone might log HR
    without HRV, a body-comp scale might log neither.
    """
    session = _FakeSession(
        hr_rows=[("iPhone", 84)],
        hrv_rows=[("Whoop", 55.0)],
    )
    repo = TimescaleHealthSnapshotRepository()
    snapshots = await repo.fetch_snapshots_by_source(session)

    by_slug = {s.slug: s for s in snapshots}
    assert by_slug["iphone"].heart_rate == 84
    assert by_slug["iphone"].hrv_latest_ms is None
    assert by_slug["whoop"].heart_rate is None
    assert by_slug["whoop"].hrv_latest_ms == 55.0


@pytest.mark.asyncio
async def test_fetch_snapshots_by_source_buckets_null_source_under_unknown() -> None:
    """NULL/empty source_id collapses to a single 'unknown' sub-device
    so legacy rows do not fragment into empty entities.
    """
    session = _FakeSession(
        hr_rows=[(None, 70), ("", 72)],
        hrv_rows=[(None, 50.0)],
    )
    repo = TimescaleHealthSnapshotRepository()
    snapshots = await repo.fetch_snapshots_by_source(session)

    # Exactly one snapshot, bucketed under "unknown".
    unknown = [s for s in snapshots if s.slug == "unknown"]
    assert len(unknown) == 1
    # Either NULL or "" HR row got picked up — the merge collapses both.
    assert unknown[0].heart_rate in (70, 72)
    assert unknown[0].hrv_latest_ms == 50.0


@pytest.mark.asyncio
async def test_fetch_snapshots_by_source_returns_empty_when_no_recent_data() -> None:
    session = _FakeSession(hr_rows=[], hrv_rows=[])
    repo = TimescaleHealthSnapshotRepository()
    snapshots = await repo.fetch_snapshots_by_source(session)
    assert snapshots == []


@pytest.mark.asyncio
async def test_fetch_snapshots_by_source_returns_results_sorted_by_slug() -> None:
    session = _FakeSession(
        hr_rows=[("Whoop", 68), ("Apple Watch", 72), ("iPhone", 84)],
        hrv_rows=[],
    )
    repo = TimescaleHealthSnapshotRepository()
    snapshots = await repo.fetch_snapshots_by_source(session)

    assert [s.slug for s in snapshots] == ["apple_watch", "iphone", "whoop"]
