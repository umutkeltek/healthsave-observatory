"""Canonical Observation store: pure mappers + repository against a fake session."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from contracts._base import Provenance
from contracts.observation import Observation
from contracts.values import CodedValue, QuantityValue
from storage.timescale.observations import (
    CanonicalObservationRepository,
    observation_columns,
    row_to_series_point,
)

_T = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
_PROV = Provenance(source_plugin_id="apple_health", sdk_version="0.1.0", captured_at=_T)
_SOURCE = UUID("11111111-1111-1111-1111-111111111111")


def _quantity_obs() -> Observation:
    return Observation(
        metric_id="vital.heart_rate",
        value=QuantityValue(
            type="quantity", value=61.0, unit="bpm", canonical_value=61.0, canonical_unit="bpm"
        ),
        interval_start=_T,
        interval_end=_T,
        source_id=_SOURCE,
        provenance=_PROV,
        normalizer_id="apple_health",
        normalizer_version="0.1.0",
        dedup_key="dk-1",
    )


def _categorical_obs() -> Observation:
    return Observation(
        metric_id="sleep.stage",
        value=CodedValue(type="categorical", code="deep", label="Deep"),
        interval_start=_T,
        interval_end=_T,
        source_id=_SOURCE,
        provenance=_PROV,
        normalizer_id="apple_health",
        normalizer_version="0.1.0",
        dedup_key="dk-2",
    )


def test_quantity_observation_flattens_to_numeric_column() -> None:
    cols = observation_columns(_quantity_obs())
    assert cols["value_type"] == "quantity"
    assert cols["numeric_value"] == 61.0
    assert cols["canonical_unit"] == "bpm"
    assert cols["code"] is None
    assert cols["quality_flags"] == []
    assert json.loads(cols["provenance"])["source_plugin_id"] == "apple_health"


def test_observation_columns_carries_stream_id() -> None:
    sid = UUID("5fd4a041-f371-51be-8b1e-8d6275534c60")
    obs = _quantity_obs()
    obs.stream_id = sid
    cols = observation_columns(obs)
    assert cols["stream_id"] == str(sid)


def test_observation_columns_stream_id_none_when_absent() -> None:
    cols = observation_columns(_quantity_obs())
    assert cols["stream_id"] is None


def test_observation_columns_include_fusion_metadata() -> None:
    obs = _quantity_obs()
    obs.exact_ingest_key = "xik:v1:polar-E1"
    obs.semantic_key = "sem:v1:polar:user:exercise:E1"
    obs.semantic_key_version = "matcher:session:v1"
    obs.aggregation_scope = "device_day_total"
    obs.is_primary = False

    cols = observation_columns(obs)

    assert cols["exact_ingest_key"] == "xik:v1:polar-E1"
    assert cols["semantic_key"] == "sem:v1:polar:user:exercise:E1"
    assert cols["semantic_key_version"] == "matcher:session:v1"
    assert cols["aggregation_scope"] == "device_day_total"
    assert cols["is_primary"] is False


def test_categorical_observation_flattens_to_code_column() -> None:
    cols = observation_columns(_categorical_obs())
    assert cols["value_type"] == "categorical"
    assert cols["code"] == "deep"
    assert cols["numeric_value"] is None
    assert cols["canonical_unit"] is None


def test_row_to_series_point_maps_fields() -> None:
    point = row_to_series_point(
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": 0.9,
            "stream_id": "5fd4a041-f371-51be-8b1e-8d6275534c60",
            "semantic_key": "sem:v1:polar:user:exercise:E1",
            "aggregation_scope": "interval_component",
            "is_primary": False,
        }
    )
    assert point.value == 61.0
    assert point.unit == "bpm"
    assert point.source_id == str(_SOURCE)
    assert point.confidence == 0.9
    assert point.stream_id == "5fd4a041-f371-51be-8b1e-8d6275534c60"
    assert point.semantic_key == "sem:v1:polar:user:exercise:E1"
    assert point.aggregation_scope == "interval_component"
    assert point.is_primary is False


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []
        self.calls: list[tuple] = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_insert_many_submits_one_row_per_observation() -> None:
    repo = CanonicalObservationRepository()
    session = _FakeSession()
    count = await repo.insert_many(session, [_quantity_obs(), _categorical_obs()])
    assert count == 2
    # one execute call, carrying a list of two param dicts (executemany)
    assert len(session.calls) == 1
    _, params = session.calls[0]
    assert isinstance(params, list)
    assert len(params) == 2
    assert {p["metric_id"] for p in params} == {"vital.heart_rate", "sleep.stage"}


@pytest.mark.asyncio
async def test_insert_many_only_updates_newer_apple_daily_total_corrections() -> None:
    repo = CanonicalObservationRepository()
    session = _FakeSession()
    daily_total = _quantity_obs().model_copy(
        update={
            "metric_id": "activity.steps",
            "exact_ingest_key": "xik:v1:apple-day",
            "aggregation_scope": "owner_all_source_day_total",
            "dedup_key": "stable-day-key",
        }
    )

    await repo.insert_many(session, [daily_total])

    statement, _params = session.calls[0]
    sql = str(statement)
    assert "ON CONFLICT (owner_id, workspace_id, dedup_key, interval_start) DO UPDATE" in sql
    assert "canonical_observations.aggregation_scope = 'owner_all_source_day_total'" in sql
    assert "EXCLUDED.aggregation_scope = 'owner_all_source_day_total'" in sql
    assert "canonical_observations.normalizer_id = 'apple_health'" in sql
    assert "EXCLUDED.normalizer_id = 'apple_health'" in sql
    assert "raw_payload_ref" in sql
    assert "captured_at" in sql
    assert "pg_input_is_valid" in sql
    assert "'bigint'" in sql
    assert "'timestamp with time zone'" in sql
    assert "EXCLUDED.created_at >= canonical_observations.created_at" in sql
    assert "status = 'active'" in sql


@pytest.mark.asyncio
async def test_insert_many_coalesces_same_batch_daily_corrections_before_upsert() -> None:
    repo = CanonicalObservationRepository()
    session = _FakeSession()
    first = _quantity_obs().model_copy(
        update={
            "metric_id": "activity.steps",
            "exact_ingest_key": "xik:v1:apple-day",
            "aggregation_scope": "owner_all_source_day_total",
            "dedup_key": "stable-day-key",
        }
    )
    corrected = first.model_copy(
        update={
            "value": QuantityValue(
                type="quantity",
                value=7_698.1,
                unit="count",
                canonical_value=7_698.1,
                canonical_unit="count",
            )
        }
    )

    submitted = await repo.insert_many(session, [first, corrected])

    _statement, params = session.calls[0]
    assert submitted == 2
    assert len(params) == 1
    assert params[0]["numeric_value"] == 7_698.1


@pytest.mark.asyncio
async def test_insert_many_empty_is_a_noop() -> None:
    repo = CanonicalObservationRepository()
    session = _FakeSession()
    assert await repo.insert_many(session, []) == 0
    assert session.calls == []


@pytest.mark.asyncio
async def test_query_series_maps_rows_to_points() -> None:
    repo = CanonicalObservationRepository()
    rows = [
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
        },
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 64.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
        },
    ]
    session = _FakeSession(rows)
    points = await repo.query_series(
        session,
        owner_id=_SOURCE,
        workspace_id=_SOURCE,
        metric_id="vital.heart_rate",
        start=_T,
        end=_T,
    )
    assert [p.value for p in points] == [61.0, 64.0]
    sql, _ = session.calls[0]
    sql_text = str(sql)
    assert "ORDER BY interval_start DESC" in sql_text
    assert "ORDER BY interval_start ASC" in sql_text


@pytest.mark.asyncio
async def test_query_fused_series_groups_by_semantic_key_and_prefers_primary() -> None:
    repo = CanonicalObservationRepository()
    rows = [
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "stream_id": "direct-stream",
            "confidence": None,
            "semantic_key": "sem:v1:polar:user:exercise:E1",
            "aggregation_scope": "interval_component",
            "is_primary": True,
        }
    ]
    session = _FakeSession(rows)

    points = await repo.query_fused_series(
        session,
        owner_id=_SOURCE,
        workspace_id=_SOURCE,
        metric_id="vital.heart_rate",
        start=_T,
        end=_T,
    )

    sql, params = session.calls[0]
    assert "COALESCE(semantic_key, id::text)" in str(sql)
    assert "is_primary DESC" in str(sql)
    assert "ORDER BY interval_start DESC" in str(sql)
    assert "ORDER BY interval_start ASC" in str(sql)
    assert params["stream_id"] is None
    assert [p.semantic_key for p in points] == ["sem:v1:polar:user:exercise:E1"]
    assert points[0].is_primary is True


@pytest.mark.asyncio
async def test_query_fused_series_many_groups_rows_by_metric_id() -> None:
    """One query, many metrics: rows come back grouped, not interleaved."""
    repo = CanonicalObservationRepository()
    rows = [
        {
            "metric_id": "vital.heart_rate",
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
            "semantic_key": None,
            "aggregation_scope": "interval_component",
            "is_primary": True,
        },
        {
            "metric_id": "sleep.stage",
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": None,
            "code": "deep",
            "canonical_unit": None,
            "source_id": _SOURCE,
            "confidence": None,
            "semantic_key": None,
            "aggregation_scope": "interval_component",
            "is_primary": True,
        },
    ]
    session = _FakeSession(rows)

    grouped = await repo.query_fused_series_many(
        session,
        owner_id=_SOURCE,
        workspace_id=_SOURCE,
        metric_ids=["vital.heart_rate", "sleep.stage"],
        start=_T,
        end=_T,
    )

    sql, params = session.calls[0]
    assert "PARTITION BY metric_id, COALESCE(semantic_key, id::text)" in str(sql)
    assert "PARTITION BY metric_id ORDER BY interval_start DESC" in str(sql)
    assert "ORDER BY metric_id, interval_start ASC" in str(sql)
    assert params["metric_ids"] == ["vital.heart_rate", "sleep.stage"]
    assert params["stream_id"] is None
    assert set(grouped) == {"vital.heart_rate", "sleep.stage"}
    assert grouped["vital.heart_rate"][0].value == 61.0
    assert grouped["sleep.stage"][0].code == "deep"


@pytest.mark.asyncio
async def test_query_fused_series_many_empty_ids_is_a_noop() -> None:
    repo = CanonicalObservationRepository()
    session = _FakeSession()

    grouped = await repo.query_fused_series_many(
        session,
        owner_id=_SOURCE,
        workspace_id=_SOURCE,
        metric_ids=[],
        start=_T,
        end=_T,
    )

    assert grouped == {}
    assert session.calls == []
