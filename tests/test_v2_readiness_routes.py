"""Tests for the additive ``GET /api/v2/readiness`` surface (Insight Action Loop card #1).

The route no longer takes a request-scoped session: ``readiness()`` fans the
two aggregate reads out through the process-level SWR cache
(``server.api.swr``) via two session-owning loaders defined in
``server.api.v2_readiness`` (``_load_canonical_coverage`` /
``_load_canonical_sources``), run concurrently with ``asyncio.gather`` so a
stale hit's background refresh can outlive any one request.

Route-assembly tests below monkeypatch ``_READINESS_REPO`` — the object both
loaders call through — with a DB-free fake. That's the seam now; the real
loaders open a real ``async_session()``, so route tests must not exercise
them against the live repo. The SQL shape of the real repository queries
(owner/status scoping, GROUP BY, provenance key) is asserted separately,
straight against the real ``_READINESS_REPO``, using the same fake-session-
with-queued-results technique the route tests used before this change.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api import v2_readiness  # noqa: E402
from server.api.v2_readiness import readiness  # noqa: E402


class _Row(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row (attribute access) — real-repo SQL-shape test only."""


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _QueueSession:
    """Async session whose successive ``execute`` calls return queued results."""

    def __init__(self, results):
        self._queue = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return self._queue.pop(0) if self._queue else _Result([])


def _raw_coverage_row(metric_id, *, count, days):
    # Timestamps are not used by the gates (count/days drive sufficiency); they
    # only flow through to the wire, so fixed values keep the test deterministic.
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return _Row(
        metric_id=metric_id,
        observation_count=count,
        days_with_data=days,
        first_at=ts,
        last_at=ts,
        last_ingested_at=ts,
    )


def _coverage_dict(metric_id, *, count, days):
    """A coverage row already shaped like the repo's dict output (post row→dict
    transform) — this is what the loader-facing fakes below hand the route."""
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return {
        "metric_id": metric_id,
        "observation_count": count,
        "days_with_data": days,
        "first_observation_at": ts,
        "last_observation_at": ts,
        "last_ingested_at": ts,
    }


def _source_dict(source_plugin_id, *, count, ts):
    return {
        "source_plugin_id": source_plugin_id,
        "observation_count": count,
        "last_ingested_at": ts,
    }


class _FakeReadinessRepo:
    """DB-free stand-in for ``_READINESS_REPO`` — the loaders call through this."""

    def __init__(self, coverage=(), sources=()):
        self._coverage = list(coverage)
        self._sources = list(sources)

    async def fetch_canonical_coverage(self, session, **kwargs):
        return self._coverage

    async def fetch_canonical_sources(self, session, **kwargs):
        return self._sources


@pytest.mark.asyncio
async def test_readiness_grades_each_metric_against_the_sufficiency_gates(monkeypatch):
    # vital.heart_rate: well over both gates (anomaly 14obs/7d, trend 21obs/14d).
    # body.weight: sparse — below both.
    monkeypatch.setattr(
        v2_readiness,
        "_READINESS_REPO",
        _FakeReadinessRepo(
            coverage=[
                _coverage_dict("vital.heart_rate", count=600, days=30),
                _coverage_dict("body.weight", count=4, days=3),
            ],
            sources=[
                _source_dict(
                    "apple_healthkit", count=604, ts=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
                )
            ],
        ),
    )

    result = await readiness()

    assert result["summary"]["metrics_with_data"] == 2
    assert result["last_observation_at"] == "2026-05-01T12:00:00+00:00"
    assert result["sources"][0]["source_plugin_id"] == "apple_healthkit"
    assert result["sources"][0]["observation_count"] == 604

    by_id = {m["metric_id"]: m for m in result["metrics"]}

    hr = by_id["vital.heart_rate"]
    assert hr["observation_count"] == 600
    assert hr["days_with_data"] == 30
    assert hr["analyzable"]["anomaly_detection"]["is_sufficient"] is True
    assert hr["analyzable"]["trend_analysis"]["is_sufficient"] is True
    # Real ontology metric → enriched with display info.
    assert hr["display_name"] != "vital.heart_rate"
    assert hr["category"] is not None

    weight = by_id["body.weight"]
    assert weight["analyzable"]["trend_analysis"]["is_sufficient"] is False
    assert weight["analyzable"]["trend_analysis"]["days_until_sufficient"] == 11  # 14 - 3
    assert "observations" in weight["analyzable"]["trend_analysis"]["missing"]


@pytest.mark.asyncio
async def test_readiness_repo_queries_canonical_store_scoped_to_active_rows():
    """SQL shape of the real repo functions.

    The loaders (``_load_canonical_coverage`` / ``_load_canonical_sources``)
    just open a session and call these through — exercised directly here
    instead of via the route, since the route itself is DB-free by design now.
    """
    coverage_session = _QueueSession(
        [_Result([_raw_coverage_row("vital.heart_rate", count=600, days=30)])]
    )
    await v2_readiness._READINESS_REPO.fetch_canonical_coverage(coverage_session)
    coverage_sql, _ = coverage_session.calls[0]
    assert "FROM canonical_observations" in coverage_sql
    assert "status = 'active'" in coverage_sql
    assert "GROUP BY metric_id" in coverage_sql

    sources_session = _QueueSession([_Result([])])
    await v2_readiness._READINESS_REPO.fetch_canonical_sources(sources_session)
    sources_sql, _ = sources_session.calls[0]
    assert "provenance->>'source_plugin_id'" in sources_sql


@pytest.mark.asyncio
async def test_readiness_empty_store_returns_empty_shape(monkeypatch):
    monkeypatch.setattr(v2_readiness, "_READINESS_REPO", _FakeReadinessRepo())

    result = await readiness()

    assert result["metrics"] == []
    assert result["sources"] == []
    assert result["last_observation_at"] is None
    assert result["last_ingested_at"] is None
    assert result["summary"]["metrics_with_data"] == 0


@pytest.mark.asyncio
async def test_readiness_unknown_metric_id_falls_back_to_raw_id(monkeypatch):
    monkeypatch.setattr(
        v2_readiness,
        "_READINESS_REPO",
        _FakeReadinessRepo(coverage=[_coverage_dict("custom.not_in_ontology", count=600, days=30)]),
    )

    result = await readiness()

    metric = result["metrics"][0]
    assert metric["metric_id"] == "custom.not_in_ontology"
    assert metric["display_name"] == "custom.not_in_ontology"
    assert metric["category"] is None
    # Grading still works off coverage alone.
    assert metric["analyzable"]["anomaly_detection"]["is_sufficient"] is True
