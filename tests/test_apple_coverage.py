"""GET /api/apple/coverage - owner-scoped per-metric latest-sample timestamp.

Companion to the /api/apple/status contract tests: coverage returns only the
newest sample per metric (for the iOS app's backfill-recovery reconciliation)
and is owner-scoped (SECURITY-002). See
``ios_app/BACKFILL_RECOVERY_RECONCILIATION.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


class _Row:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class CoverageFakeSession:
    """Populated latest for heart_rate + hrv, None elsewhere; fail_metric raises."""

    _latest = {"heart_rate": "2026-07-14T08:03:00Z", "hrv": "2026-07-14T07:55:00Z"}

    def __init__(self, *, fail_metric: str | None = None):
        self.fail_metric = fail_metric
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if self.fail_metric and f"FROM {self.fail_metric}" in sql:
            raise RuntimeError("database is unavailable")
        latest = None
        for metric, value in self._latest.items():
            if f"FROM {metric}" in sql:
                latest = value
                break
        return _Row(row=(latest,))


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_coverage_returns_per_metric_latest():
    session = CoverageFakeSession()

    result = await server.apple_coverage(_FakeRequest(), session)

    # flat {metric: iso_or_none} -- no wrapper, mirroring /api/apple/status
    assert "status" not in result and "counts" not in result
    assert set(result) == {
        "heart_rate", "hrv", "blood_oxygen", "daily_activity",
        "sleep_sessions", "workouts", "quantity_samples",
    }
    assert result["heart_rate"] == "2026-07-14T08:03:00Z"
    assert result["hrv"] == "2026-07-14T07:55:00Z"
    # metrics with no data -> None: reconciliation must NOT clear the flag
    assert result["blood_oxygen"] is None
    assert result["workouts"] is None


@pytest.mark.asyncio
async def test_coverage_is_owner_scoped():
    """SECURITY-002: the latest-sample query is filtered by owner_id."""
    session = CoverageFakeSession()

    await server.apple_coverage(_FakeRequest(), session)

    hr = [(sql, p) for sql, p in session.calls if "FROM heart_rate" in sql]
    assert hr, "expected a heart_rate coverage query"
    sql, params = hr[0]
    assert "owner_id = :owner_id" in sql
    assert "owner_id" in params


@pytest.mark.asyncio
async def test_coverage_degrades_a_failing_metric_to_none():
    # a single metric query failing must not 500 the response; the iOS
    # reconciliation treats None conservatively (keeps the flag).
    session = CoverageFakeSession(fail_metric="workouts")

    result = await server.apple_coverage(_FakeRequest(), session)

    assert result["heart_rate"] == "2026-07-14T08:03:00Z"
    assert result["workouts"] is None
    assert len(result) == 7
