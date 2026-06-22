"""Polar AccessLink plugin ingest path."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402
from plugin_sdk import load_manifest  # noqa: E402
from plugins.sources.polar import POLAR_PROVIDER, PolarSource  # noqa: E402
from plugins.sources.polar.fetch import PATH_EXERCISES  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "polar"


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class _HttpClient:
    response: _Response
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


@dataclass
class _IngestCall:
    metric: str
    samples: list[dict]
    device_id: int | str
    owner_id: Any


class _Storage:
    def __init__(self):
        self.ingest_calls: list[_IngestCall] = []

    async def get_or_create_device(self, session, device_type):
        return f"device:{device_type}"

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        self.ingest_calls.append(
            _IngestCall(metric=metric, samples=samples, device_id=device_id, owner_id=owner_id)
        )
        return len(samples)


@dataclass
class _TokenStore:
    token: OAuthToken | None

    async def get_token(self, session, *, provider, owner_id):
        return self.token


def _plugin() -> PolarSource:
    return PolarSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))


def _token() -> OAuthToken:
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=POLAR_PROVIDER,
        access_token="AT",
        refresh_token=None,
        expires_at=None,
        metadata={"x_user_id": 10579},
    )


@pytest.mark.asyncio
async def test_polar_ingest_returns_zero_when_no_token_stored():
    result = await _plugin().ingest(
        {
            "storage": _Storage(),
            "session": object(),
            "http_client": _HttpClient(_Response(200, {"exercises": []})),
            "token_store": _TokenStore(None),
        }
    )

    assert result == {"accepted": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_polar_ingest_fetches_exercises_and_writes_existing_storage_port():
    storage = _Storage()
    http = _HttpClient(
        _Response(
            200,
            {
                "exercises": [
                    {
                        "id": "2AC312F",
                        "device_id": "1111AAAA",
                        "start_time": "2008-10-13T10:40:02",
                        "duration": "PT30M",
                        "sport": "RUNNING",
                    }
                ]
            },
        )
    )

    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": _TokenStore(_token()),
        }
    )

    assert result == {"accepted": 2, "rejected": 0}
    assert http.calls[0]["url"].endswith(PATH_EXERCISES)
    assert [call.metric for call in storage.ingest_calls] == [
        "workouts",
        "exercise_duration_seconds",
    ]
    assert storage.ingest_calls[0].device_id == "device:Polar"
    assert storage.ingest_calls[0].samples[0]["provider_object_id"] == "2AC312F"
