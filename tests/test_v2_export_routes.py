"""Tests for the additive ``GET /api/v2/export`` surface."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.api.v2_export as v2_export  # noqa: E402
from server.api.v2_export import export_data, list_export_metrics  # noqa: E402


class _FakeRepo:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def list_available_metrics(self, session, *, owner_id):
        self.calls.append(("list_available_metrics", {"session": session, "owner_id": owner_id}))
        return [{"metric": "heart_rate", "count": 1}]

    async def export_metric_json(
        self,
        session,
        *,
        metric,
        owner_id,
        date_from=None,
        date_to=None,
        limit=None,
    ):
        self.calls.append(
            (
                "export_metric_json",
                {
                    "session": session,
                    "metric": metric,
                    "owner_id": owner_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": limit,
                },
            )
        )
        if metric == "unknown":
            raise KeyError(metric)
        return [{"metric": metric, "rows": 1}]

    async def export_metric_csv(
        self,
        session,
        *,
        metric,
        owner_id,
        date_from=None,
        date_to=None,
        limit=None,
    ):
        self.calls.append(
            (
                "export_metric_csv",
                {
                    "session": session,
                    "metric": metric,
                    "owner_id": owner_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": limit,
                },
            )
        )
        if metric == "unknown":
            raise KeyError(metric)
        return "time,bpm\n2026-05-01T12:00:00+00:00,62\n"

    async def export_all_json(
        self,
        session,
        *,
        owner_id,
        date_from=None,
        date_to=None,
        limit=None,
    ):
        self.calls.append(
            (
                "export_all_json",
                {
                    "session": session,
                    "owner_id": owner_id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": limit,
                },
            )
        )
        return {"heart_rate": [{"rows": 1}]}


async def _read_streaming_response(response: StreamingResponse) -> str:
    parts: list[str] = []
    async for chunk in response.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


@pytest.mark.asyncio
async def test_list_export_metrics_delegates_to_repository(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)
    session = object()

    result = await list_export_metrics(session=session)

    assert result == [{"metric": "heart_rate", "count": 1}]
    assert repo.calls[0][0] == "list_available_metrics"


@pytest.mark.asyncio
async def test_export_data_returns_json_for_single_metric(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)
    session = object()

    result = await export_data(metric="heart_rate", format="json", session=session)

    assert result == [{"metric": "heart_rate", "rows": 1}]
    assert repo.calls[0][0] == "export_metric_json"


@pytest.mark.asyncio
async def test_export_data_returns_csv_stream_for_single_metric(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)
    session = object()

    response = await export_data(metric="heart_rate", format="csv", session=session)

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/csv"
    assert (
        response.headers["Content-Disposition"] == "attachment; filename=healthsave_heart_rate.csv"
    )
    assert await _read_streaming_response(response) == "time,bpm\n2026-05-01T12:00:00+00:00,62\n"


@pytest.mark.asyncio
async def test_export_data_rejects_csv_export_for_all_metrics(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)

    with pytest.raises(HTTPException) as excinfo:
        await export_data(metric="all", format="csv", session=object())

    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_export_data_maps_unknown_metric_to_404(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)

    with pytest.raises(HTTPException) as excinfo:
        await export_data(metric="unknown", format="json", session=object())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_export_data_returns_export_all_json(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)
    session = object()

    result = await export_data(metric="all", format="json", session=session)

    assert result == {"heart_rate": [{"rows": 1}]}
    assert repo.calls[0][0] == "export_all_json"


@pytest.mark.asyncio
async def test_export_data_days_shortcut_resolves_date_window(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)

    await export_data(metric="heart_rate", format="json", days=7, session=object())

    _, params = repo.calls[0]
    assert isinstance(params["date_from"], date)
    assert isinstance(params["date_to"], date)
    assert params["date_from"] is not None
    assert params["date_to"] is not None
