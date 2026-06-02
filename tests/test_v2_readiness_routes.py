"""Tests for the additive ``GET /api/v2/readiness`` surface (Insight Action Loop card #1).

FakeSession discipline — no live DB. The route issues two queries (per-metric
coverage, then source attribution), so the fake session returns queued results
in that order. Asserts the coverage→sufficiency grading, source/freshness
rollup, and the empty-store shape.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.v2_readiness import readiness  # noqa: E402


class _Row(SimpleNamespace):
    """Stand-in for a SQLAlchemy Row (attribute access)."""


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


def _coverage_row(metric_id, *, count, days):
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


@pytest.mark.asyncio
async def test_readiness_grades_each_metric_against_the_sufficiency_gates():
    # vital.heart_rate: well over both gates (anomaly 14obs/7d, trend 21obs/14d).
    # body.weight: sparse — below both.
    coverage = _Result(
        [
            _coverage_row("vital.heart_rate", count=600, days=30),
            _coverage_row("body.weight", count=4, days=3),
        ]
    )
    sources = _Result(
        [
            _Row(
                source_plugin_id="apple_healthkit",
                observation_count=604,
                last_ingested_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            )
        ]
    )
    session = _QueueSession([coverage, sources])

    result = await readiness(session=session)

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
async def test_readiness_queries_canonical_store_scoped_to_active_rows():
    session = _QueueSession(
        [_Result([_coverage_row("vital.heart_rate", count=600, days=30)]), _Result([])]
    )
    await readiness(session=session)
    coverage_sql, _ = session.calls[0]
    assert "FROM canonical_observations" in coverage_sql
    assert "status = 'active'" in coverage_sql
    assert "GROUP BY metric_id" in coverage_sql
    sources_sql, _ = session.calls[1]
    assert "provenance->>'source_plugin_id'" in sources_sql


@pytest.mark.asyncio
async def test_readiness_empty_store_returns_empty_shape():
    session = _QueueSession([_Result([]), _Result([])])

    result = await readiness(session=session)

    assert result["metrics"] == []
    assert result["sources"] == []
    assert result["last_observation_at"] is None
    assert result["last_ingested_at"] is None
    assert result["summary"]["metrics_with_data"] == 0


@pytest.mark.asyncio
async def test_readiness_unknown_metric_id_falls_back_to_raw_id():
    coverage = _Result([_coverage_row("custom.not_in_ontology", count=600, days=30)])
    session = _QueueSession([coverage, _Result([])])

    result = await readiness(session=session)

    metric = result["metrics"][0]
    assert metric["metric_id"] == "custom.not_in_ontology"
    assert metric["display_name"] == "custom.not_in_ontology"
    assert metric["category"] is None
    # Grading still works off coverage alone.
    assert metric["analyzable"]["anomaly_detection"]["is_sufficient"] is True
