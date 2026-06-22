"""Polar AccessLink `/v3/exercises` fetch helper tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.polar.fetch import (  # noqa: E402
    PATH_EXERCISES,
    PolarFetchError,
    fetch_exercises,
)
from plugins.sources.polar.oauth import POLAR_API_BASE  # noqa: E402


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any] | list[dict[str, Any]]
    text: str = ""
    _raise_on_json: bool = False

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self.payload


@dataclass
class _HttpClient:
    response: _Response
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


@pytest.mark.asyncio
async def test_fetch_exercises_uses_v3_exercises_and_bearer_token():
    client = _HttpClient(
        _Response(
            200,
            {
                "exercises": [
                    {"id": "2AC312F", "duration": "PT2H44M", "start_time": "2008-10-13T10:40:02"}
                ]
            },
        )
    )

    exercises = await fetch_exercises(
        client,
        access_token="AT",
        since=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert exercises[0]["id"] == "2AC312F"
    assert client.calls == [
        {
            "url": f"{POLAR_API_BASE}{PATH_EXERCISES}",
            "params": {"samples": "false", "zones": "false"},
            "headers": {"Authorization": "Bearer AT", "Accept": "application/json"},
        }
    ]


@pytest.mark.asyncio
async def test_fetch_exercises_accepts_list_payload():
    client = _HttpClient(_Response(200, [{"id": "E1"}]))

    exercises = await fetch_exercises(client, access_token="AT", since=None)

    assert exercises == [{"id": "E1"}]


@pytest.mark.asyncio
async def test_fetch_exercises_raises_on_non_200():
    client = _HttpClient(_Response(403, {}, text="forbidden"))

    with pytest.raises(PolarFetchError, match="HTTP 403"):
        await fetch_exercises(client, access_token="AT", since=None)


@pytest.mark.asyncio
async def test_fetch_exercises_raises_on_non_json():
    client = _HttpClient(_Response(200, {}, _raise_on_json=True))

    with pytest.raises(PolarFetchError, match="non-JSON"):
        await fetch_exercises(client, access_token="AT", since=None)
