"""v2 read API: /api/v2/metrics + /api/v2/metrics/{id}/series + /api/v2/series."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from server.api.v2_metrics import (
    MAX_SERIES_BATCH_IDS,
    list_metrics,
    metric_series,
    metric_series_batch,
)

_T = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
_SLEEP_END = _T + timedelta(minutes=30)
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
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
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
    assert body["points"][0]["interval_end"] == _T.isoformat()
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
async def test_metric_series_exposes_capture_context() -> None:
    """Plan 2026-09-03: the series endpoint surfaces the per-sample
    tz offset and HR motion context the v2 ingest stamped into
    provenance (Eric's asks #4 + #5 — local-day bucketing and
    resting-quality separation). Absent context stays null."""
    rows = [
        {
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 52.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
            "tz_offset_minutes": -240,
            "motion_context": "sedentary",
        },
        {
            "interval_start": _T + timedelta(minutes=1),
            "interval_end": _T + timedelta(minutes=1),
            "numeric_value": 54.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
            # v1-shaped row: no capture context keys at all
        },
    ]
    body = await metric_series("vital.heart_rate", range="7d", session=_FakeSession(rows))
    assert body["points"][0]["tz_offset_minutes"] == -240
    assert body["points"][0]["motion_context"] == "sedentary"
    assert body["points"][1]["tz_offset_minutes"] is None
    assert body["points"][1]["motion_context"] is None


@pytest.mark.asyncio
async def test_metric_series_accepts_stream_id_param() -> None:
    """The optional stream_id filter param is accepted (absent = fused)."""
    body = await metric_series(
        "vital.heart_rate", range="7d", stream_id=str(_SOURCE), session=_FakeSession([])
    )
    assert body["points"] == []


@pytest.mark.asyncio
async def test_metric_series_without_stream_id_uses_fused_read() -> None:
    session = _FakeSession([])
    await metric_series("vital.heart_rate", range="7d", session=session)

    sql, _params = session.calls[0]
    assert "COALESCE(semantic_key, id::text)" in str(sql)


@pytest.mark.asyncio
async def test_metric_series_with_stream_id_uses_raw_read() -> None:
    session = _FakeSession([])
    await metric_series("vital.heart_rate", range="7d", stream_id=_SOURCE, session=session)

    sql, _params = session.calls[0]
    assert "COALESCE(semantic_key, id::text)" not in str(sql)


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


@pytest.mark.asyncio
async def test_batch_series_returns_item_per_metric() -> None:
    """Rows come back tagged with metric_id; a known id with no rows gets []."""
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
        },
    ]
    body = await metric_series_batch(
        ids="vital.heart_rate,sleep.stage", range="7d", session=_FakeSession(rows)
    )
    assert body["range"] == "7d"
    assert len(body["series"]) == 2
    first = body["series"][0]
    assert first["metric"]["id"] == "vital.heart_rate"
    assert first["points"][0]["value"] == 61.0
    assert first["points"][0]["unit"] == "bpm"
    assert body["series"][1]["metric"]["id"] == "sleep.stage"
    assert body["series"][1]["points"] == []


@pytest.mark.asyncio
async def test_batch_series_unknown_id_is_per_item_error() -> None:
    """One bad id reports inline; the rest of the batch still returns."""
    body = await metric_series_batch(
        ids="not.a.metric,vital.heart_rate", range="7d", session=_FakeSession([])
    )
    assert body["series"][0] == {"metric_id": "not.a.metric", "error": "unknown metric"}
    assert body["series"][1]["metric"]["id"] == "vital.heart_rate"
    assert body["series"][1]["points"] == []


@pytest.mark.asyncio
async def test_batch_series_stream_id_none_issues_one_fused_query() -> None:
    """The N+1 fix: mixed known/unknown ids in original order, ONE query call."""
    rows = [
        {
            "metric_id": "sleep.stage",
            "interval_start": _T,
            "interval_end": _SLEEP_END,
            "numeric_value": None,
            "code": "deep",
            "canonical_unit": None,
            "source_id": _SOURCE,
            "confidence": None,
        },
        {
            "metric_id": "vital.heart_rate",
            "interval_start": _T,
            "interval_end": _T,
            "numeric_value": 61.0,
            "code": None,
            "canonical_unit": "bpm",
            "source_id": _SOURCE,
            "confidence": None,
        },
    ]
    session = _FakeSession(rows)

    body = await metric_series_batch(
        ids="vital.heart_rate,not.a.metric,sleep.stage", range="7d", session=session
    )

    # exactly one round trip for the whole batch, not one per known id
    assert len(session.calls) == 1
    _sql, params = session.calls[0]
    assert params["metric_ids"] == ["vital.heart_rate", "sleep.stage"]
    assert params["stream_id"] is None

    ids_in_order = [
        item.get("metric", {}).get("id") or item.get("metric_id") for item in body["series"]
    ]
    assert ids_in_order == ["vital.heart_rate", "not.a.metric", "sleep.stage"]
    assert body["series"][1] == {"metric_id": "not.a.metric", "error": "unknown metric"}
    assert body["series"][0]["points"][0]["value"] == 61.0
    assert body["series"][2]["points"][0]["interval_end"] == _SLEEP_END.isoformat()
    assert body["series"][2]["points"][0]["code"] == "deep"


@pytest.mark.asyncio
async def test_batch_series_known_id_with_zero_points() -> None:
    """A known metric with no rows in range still gets an item, points: []."""
    body = await metric_series_batch(
        ids="vital.heart_rate,sleep.stage", range="7d", session=_FakeSession([])
    )
    assert body["series"][0]["metric"]["id"] == "vital.heart_rate"
    assert body["series"][0]["points"] == []
    assert body["series"][1]["metric"]["id"] == "sleep.stage"
    assert body["series"][1]["points"] == []


@pytest.mark.asyncio
async def test_batch_series_dedupes_and_ignores_blank_ids() -> None:
    body = await metric_series_batch(
        ids=" vital.heart_rate, ,vital.heart_rate,", range="7d", session=_FakeSession([])
    )
    assert len(body["series"]) == 1


@pytest.mark.asyncio
async def test_batch_series_empty_ids_422() -> None:
    with pytest.raises(HTTPException) as exc:
        await metric_series_batch(ids=" , ", range="7d", session=_FakeSession())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_batch_series_too_many_ids_422() -> None:
    ids = ",".join(f"fake.metric_{i}" for i in range(MAX_SERIES_BATCH_IDS + 1))
    with pytest.raises(HTTPException) as exc:
        await metric_series_batch(ids=ids, range="7d", session=_FakeSession())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_batch_series_unknown_range_422() -> None:
    with pytest.raises(HTTPException) as exc:
        await metric_series_batch(ids="vital.heart_rate", range="bogus", session=_FakeSession())
    assert exc.value.status_code == 422
