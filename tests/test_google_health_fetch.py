"""Google Health API data point fetch helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.google_health.fetch import (  # noqa: E402
    DATA_TYPE_STEPS,
    GOOGLE_HEALTH_API_BASE,
    GoogleHealthFetchError,
    fetch_data_points,
)


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""
    _raise_on_json: bool = False

    def json(self) -> dict[str, Any]:
        if self._raise_on_json:
            raise ValueError("not json")
        return self.payload


@dataclass
class _HttpClient:
    responses: list[_Response]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url: str, *, params=None, headers=None) -> _Response:
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_steps_uses_v4_data_points_and_documented_filter() -> None:
    client = _HttpClient(
        [
            _Response(
                200,
                {
                    "dataPoints": [
                        {
                            "name": "users/me/dataTypes/steps/dataPoints/step-a",
                            "steps": {"count": "42"},
                        }
                    ]
                },
            )
        ]
    )

    points = await fetch_data_points(
        client,
        access_token="access-token",
        data_type=DATA_TYPE_STEPS,
        since=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert points[0]["name"].endswith("step-a")
    assert client.calls == [
        {
            "url": f"{GOOGLE_HEALTH_API_BASE}/v4/users/me/dataTypes/steps/dataPoints",
            "params": {
                "pageSize": "1000",
                "filter": 'steps.interval.start_time >= "2026-06-01T00:00:00Z"',
            },
            "headers": {
                "Authorization": "Bearer access-token",
                "Accept": "application/json",
            },
        }
    ]


@pytest.mark.asyncio
async def test_fetch_data_points_paginates_next_page_token() -> None:
    client = _HttpClient(
        [
            _Response(200, {"dataPoints": [{"name": "first"}], "nextPageToken": "NEXT"}),
            _Response(200, {"dataPoints": [{"name": "second"}]}),
        ]
    )

    points = await fetch_data_points(client, access_token="access-token", data_type=DATA_TYPE_STEPS)

    assert [point["name"] for point in points] == ["first", "second"]
    assert client.calls[1]["params"]["pageToken"] == "NEXT"


@pytest.mark.asyncio
async def test_fetch_data_points_raises_on_http_error() -> None:
    client = _HttpClient([_Response(403, {"error": "denied"}, text="denied")])

    with pytest.raises(GoogleHealthFetchError, match="HTTP 403"):
        await fetch_data_points(client, access_token="access-token", data_type=DATA_TYPE_STEPS)


@pytest.mark.asyncio
async def test_fetch_data_points_raises_on_non_json_body() -> None:
    client = _HttpClient([_Response(200, {}, _raise_on_json=True)])

    with pytest.raises(GoogleHealthFetchError, match="non-JSON"):
        await fetch_data_points(client, access_token="access-token", data_type=DATA_TYPE_STEPS)
