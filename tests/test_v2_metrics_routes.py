"""v2 read API: /api/v2/metrics + /api/v2/metrics/{id}/series."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from server.api.v2_metrics import list_metrics, metric_series

_T = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
_SOURCE = UUID("11111111-1111-1111-1111-111111111111")


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def execute(self, statement, params=None):
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_list_metrics_returns_full_catalog() -> None:
    metrics = await list_metrics()
    assert len(metrics) >= 140
    ids = {m["id"] for m in metrics}
    assert "vital.heart_rate" in ids
    assert "sleep.stage" in ids
    sample = next(m for m in metrics if m["id"] == "vital.heart_rate")
    assert sample["value_type"] == "quantity"
    assert sample["canonical_unit"] == "bpm"


@pytest.mark.asyncio
async def test_metric_series_returns_mapped_points() -> None:
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
    ]
    body = await metric_series("vital.heart_rate", range="7d", session=_FakeSession(rows))
    assert body["metric"]["id"] == "vital.heart_rate"
    assert body["range"] == "7d"
    assert len(body["points"]) == 1
    assert body["points"][0]["value"] == 61.0
    assert body["points"][0]["unit"] == "bpm"


@pytest.mark.asyncio
async def test_metric_series_carries_stream_id() -> None:
    """Each point exposes its stream_id (the per-device provenance axis)."""
    stream = UUID("22222222-2222-2222-2222-222222222222")
    rows = [
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "stream_id": stream,
            "confidence": None,
        },
    ]
    body = await metric_series("vital.heart_rate", range="7d", session=_FakeSession(rows))
    assert body["points"][0]["stream_id"] == str(stream)


@pytest.mark.asyncio
async def test_metric_series_accepts_stream_id_param() -> None:
    """The optional stream_id filter param is accepted (absent = fused)."""
    body = await metric_series(
        "vital.heart_rate", range="7d", stream_id=str(_SOURCE), session=_FakeSession([])
    )
    assert body["points"] == []


@pytest.mark.asyncio
async def test_metric_series_unknown_metric_404() -> None:
    with pytest.raises(HTTPException) as exc:
        await metric_series("not.a.metric", range="7d", session=_FakeSession())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_metric_series_unknown_range_422() -> None:
    with pytest.raises(HTTPException) as exc:
        await metric_series("vital.heart_rate", range="bogus", session=_FakeSession())
    assert exc.value.status_code == 422
