"""Tests for the Whoop paginated API client + per-resource fetchers.

The fetchers are pure HTTP-with-pagination helpers; tests inject a
recording ``HttpClient`` double that returns synthetic Whoop-shaped
responses. Cover:

  * single-page response (no ``next_token``).
  * multi-page response (cursor passed back as ``nextToken``).
  * since= passes ``start`` as Whoop-formatted ISO with a Z suffix.
  * non-200 surfaces as :class:`WhoopFetchError`.
  * malformed JSON surfaces as :class:`WhoopFetchError`.
  * runaway pagination is bounded by ``max_pages``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.whoop.fetch import (  # noqa: E402
    PATH_BODY,
    PATH_CYCLE,
    PATH_RECOVERY,
    PATH_SLEEP,
    PATH_WORKOUT,
    WhoopFetchError,
    fetch_body_measurement,
    fetch_cycles,
    fetch_recovery,
    fetch_sleep,
    fetch_workouts,
    paginated_get,
)


@dataclass
class _FakeResponse:
    status_code: int
    payload: dict[str, Any]
    text: str = ""
    _raise_on_json: bool = False

    def json(self) -> dict[str, Any]:
        if self._raise_on_json:
            raise ValueError("not json")
        return self.payload


@dataclass
class _RecordingHttpClient:
    """Returns a queue of responses in order; records every GET call."""

    responses: list[_FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        if not self.responses:
            raise AssertionError("test ran out of canned responses")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_paginated_get_returns_single_page_when_no_next_token():
    client = _RecordingHttpClient(
        responses=[
            _FakeResponse(
                status_code=200,
                payload={"records": [{"id": 1}, {"id": 2}], "next_token": None},
            )
        ]
    )
    records = await paginated_get(client, access_token="AT", path=PATH_RECOVERY, since=None)
    assert records == [{"id": 1}, {"id": 2}]
    assert len(client.calls) == 1
    assert client.calls[0]["url"].endswith(PATH_RECOVERY)
    assert client.calls[0]["headers"]["Authorization"] == "Bearer AT"
    assert client.calls[0]["params"].get("nextToken") is None


@pytest.mark.asyncio
async def test_paginated_get_walks_multi_page_with_next_token_cursor():
    client = _RecordingHttpClient(
        responses=[
            _FakeResponse(
                status_code=200,
                payload={"records": [{"id": 1}], "next_token": "page2"},
            ),
            _FakeResponse(
                status_code=200,
                payload={"records": [{"id": 2}], "next_token": "page3"},
            ),
            _FakeResponse(
                status_code=200,
                payload={"records": [{"id": 3}], "next_token": None},
            ),
        ]
    )
    records = await paginated_get(client, access_token="AT", path=PATH_SLEEP, since=None)
    assert [r["id"] for r in records] == [1, 2, 3]
    assert len(client.calls) == 3
    # Cursor flows: first call has no nextToken; second has "page2"; third has "page3".
    assert "nextToken" not in client.calls[0]["params"]
    assert client.calls[1]["params"]["nextToken"] == "page2"
    assert client.calls[2]["params"]["nextToken"] == "page3"


@pytest.mark.asyncio
async def test_paginated_get_formats_since_as_iso_with_z_suffix():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={"records": []})]
    )
    since = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
    await paginated_get(client, access_token="AT", path=PATH_WORKOUT, since=since)
    assert client.calls[0]["params"]["start"] == "2026-05-22T12:00:00Z"


@pytest.mark.asyncio
async def test_paginated_get_raises_on_non_200():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=401, payload={}, text="unauthorized")]
    )
    with pytest.raises(WhoopFetchError):
        await paginated_get(client, access_token="bad", path=PATH_RECOVERY, since=None)


@pytest.mark.asyncio
async def test_paginated_get_raises_on_non_json_body():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={}, _raise_on_json=True)]
    )
    with pytest.raises(WhoopFetchError):
        await paginated_get(client, access_token="AT", path=PATH_RECOVERY, since=None)


@pytest.mark.asyncio
async def test_paginated_get_raises_when_max_pages_exceeded():
    # Make a generator-style infinite pager by re-cycling a response that
    # always claims more pages exist.
    responses = [
        _FakeResponse(
            status_code=200,
            payload={"records": [{"id": i}], "next_token": "more"},
        )
        for i in range(10)
    ]
    client = _RecordingHttpClient(responses=responses)
    with pytest.raises(WhoopFetchError):
        await paginated_get(
            client,
            access_token="AT",
            path=PATH_RECOVERY,
            since=None,
            max_pages=5,
        )
    assert len(client.calls) == 5


@pytest.mark.asyncio
async def test_fetch_recovery_uses_recovery_path():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={"records": []})]
    )
    await fetch_recovery(client, access_token="AT")
    assert client.calls[0]["url"].endswith(PATH_RECOVERY)


@pytest.mark.asyncio
async def test_fetch_sleep_uses_sleep_path():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={"records": []})]
    )
    await fetch_sleep(client, access_token="AT")
    assert client.calls[0]["url"].endswith(PATH_SLEEP)


@pytest.mark.asyncio
async def test_fetch_workouts_uses_workout_path():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={"records": []})]
    )
    await fetch_workouts(client, access_token="AT")
    assert client.calls[0]["url"].endswith(PATH_WORKOUT)


@pytest.mark.asyncio
async def test_fetch_cycles_uses_cycle_path():
    client = _RecordingHttpClient(
        responses=[_FakeResponse(status_code=200, payload={"records": []})]
    )
    await fetch_cycles(client, access_token="AT")
    assert client.calls[0]["url"].endswith(PATH_CYCLE)


@pytest.mark.asyncio
async def test_fetch_body_measurement_uses_body_path_and_returns_single_object():
    client = _RecordingHttpClient(
        responses=[
            _FakeResponse(
                status_code=200,
                payload={
                    "height_meter": 1.78,
                    "weight_kilogram": 75.0,
                    "max_heart_rate": 195,
                },
            )
        ]
    )
    record = await fetch_body_measurement(client, access_token="AT")
    assert record == {
        "height_meter": 1.78,
        "weight_kilogram": 75.0,
        "max_heart_rate": 195,
    }
    assert client.calls[0]["url"].endswith(PATH_BODY)
    assert client.calls[0]["headers"]["Authorization"] == "Bearer AT"
