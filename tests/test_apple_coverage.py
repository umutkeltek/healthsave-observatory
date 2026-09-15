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

    # the flat {table: ts_or_none} keys mirror /api/apple/status, plus the additive
    # per-wire-metric map the iOS app decodes (2026-09-15)
    assert "status" not in result and "counts" not in result
    assert set(result) == {
        "heart_rate",
        "hrv",
        "blood_oxygen",
        "daily_activity",
        "sleep_sessions",
        "workouts",
        "quantity_samples",
        "metrics",
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
    assert len(result) == 8


# --- per-wire-metric map (2026-09-15) -----------------------------------------------------
# The iOS app decodes {"metrics": {<wire metric>: <ISO 8601 UTC ms Z>}}. The flat table keys
# never matched (wrapper, key vocabulary and timestamp format all differed), so the app read
# every answer as unreachable and Recovery-lane attestation never cleared anything here.

from datetime import UTC, datetime  # noqa: E402

from server.api import coverage as coverage_module  # noqa: E402


class _FakeCoverageRepo:
    def __init__(self, rows=None, *, fail: bool = False):
        self.rows = rows or []
        self.fail = fail
        self.calls: list[dict] = []

    async def fetch_canonical_coverage(self, session, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("canonical store unavailable")
        return self.rows


@pytest.fixture
def fake_repo(monkeypatch):
    def install(repo):
        monkeypatch.setattr(coverage_module, "_COVERAGE_REPO", repo)
        return repo

    return install


@pytest.mark.asyncio
async def test_coverage_names_each_wire_metric_in_the_apps_shape(fake_repo):
    repo = fake_repo(
        _FakeCoverageRepo(
            [
                {
                    "metric_id": "vital.hrv_sdnn",
                    "last_observation_at": datetime(2026, 9, 14, 12, 8, 0, 503000, tzinfo=UTC),
                },
                {
                    "metric_id": "activity.steps",
                    "last_observation_at": datetime(2026, 9, 13, 22, 0, tzinfo=UTC),
                },
            ]
        )
    )

    result = await server.apple_coverage(_FakeRequest(), CoverageFakeSession())

    metrics = result["metrics"]
    assert metrics["heart_rate_variability"] == "2026-09-14T12:08:00.503Z"
    assert metrics["step_count"] == "2026-09-13T22:00:00.000Z"
    assert "workouts" not in metrics, "no data: absent, so the app keeps its flag"
    assert repo.calls and "owner_id" in repo.calls[0], "owner-scoped (SECURITY-002)"


@pytest.mark.asyncio
async def test_coverage_metrics_fall_back_to_legacy_families(fake_repo):
    class LegacySession(CoverageFakeSession):
        _latest = {"daily_activity": "2026-09-14", "sleep_sessions": "2026-09-13 21:40:00+00:00"}

    fake_repo(_FakeCoverageRepo([]))

    result = await server.apple_coverage(_FakeRequest(), LegacySession())

    assert result["metrics"]["activity_summaries"] == "2026-09-14T00:00:00.000Z"
    assert result["metrics"]["sleep_analysis"] == "2026-09-13T21:40:00.000Z"


@pytest.mark.asyncio
async def test_a_failing_canonical_read_never_500s(fake_repo):
    fake_repo(_FakeCoverageRepo(fail=True))

    result = await server.apple_coverage(_FakeRequest(), CoverageFakeSession())

    assert result["heart_rate"] == "2026-07-14T08:03:00Z", "flat keys unaffected"
    assert isinstance(result["metrics"], dict)


def test_every_apple_wire_metric_maps_from_its_canonical_id():
    names = coverage_module.apple_wire_names()
    assert names["vital.hrv_sdnn"] == ["heart_rate_variability"]
    assert names["activity.steps"] == ["step_count"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 9, 14, 12, 8, 0, 503999, tzinfo=UTC), "2026-09-14T12:08:00.503Z"),
        (datetime(2026, 9, 14, 12, 8), "2026-09-14T12:08:00.000Z"),
        ("2026-09-14", "2026-09-14T00:00:00.000Z"),
        ("2026-09-14 12:06:00+00:00", "2026-09-14T12:06:00.000Z"),
        (None, None),
        ("not a date", None),
    ],
)
def test_wire_timestamp_is_iso_utc_milliseconds_z(value, expected):
    assert coverage_module.wire_timestamp(value) == expected
