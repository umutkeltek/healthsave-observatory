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
        }
    )
    assert point.value == 61.0
    assert point.unit == "bpm"
    assert point.source_id == str(_SOURCE)
    assert point.confidence == 0.9


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
