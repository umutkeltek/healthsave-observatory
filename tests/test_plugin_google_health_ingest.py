"""Google Health API plugin ingest path."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402
from plugin_sdk import load_manifest  # noqa: E402
from plugins.sources.google_health import GOOGLE_HEALTH_PROVIDER, GoogleHealthSource  # noqa: E402
from plugins.sources.google_health.fetch import DATA_TYPE_STEPS  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "google_health"


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

    async def get(self, url: str, *, params=None, headers=None) -> _Response:
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


@dataclass
class _IngestCall:
    metric: str
    samples: list[dict]
    device_id: int | str
    owner_id: Any


class _Storage:
    def __init__(self) -> None:
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
        assert provider == GOOGLE_HEALTH_PROVIDER
        assert owner_id == DEFAULT_OWNER_ID
        return self.token


def _token() -> OAuthToken:
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=GOOGLE_HEALTH_PROVIDER,
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=None,
        scopes=(),
        metadata={},
    )


def _plugin() -> GoogleHealthSource:
    return GoogleHealthSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))


@pytest.mark.asyncio
async def test_google_health_ingest_noops_when_token_missing() -> None:
    result = await _plugin().ingest(
        {
            "storage": _Storage(),
            "session": object(),
            "http_client": _HttpClient(_Response(200, {"dataPoints": []})),
            "token_store": _TokenStore(None),
        }
    )

    assert result == {"accepted": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_google_health_ingest_fetches_steps_and_writes_existing_storage_port() -> None:
    storage = _Storage()
    http = _HttpClient(
        _Response(
            200,
            {
                "dataPoints": [
                    {
                        "name": "users/me/dataTypes/steps/dataPoints/step-a",
                        "steps": {
                            "interval": {"startTime": "2026-06-01T08:00:00Z"},
                            "count": "42",
                        },
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

    assert result == {"accepted": 1, "rejected": 0}
    assert DATA_TYPE_STEPS in http.calls[0]["url"]
    assert [call.metric for call in storage.ingest_calls] == ["step_count"]
    assert storage.ingest_calls[0].device_id == "device:Google Health"
    assert storage.ingest_calls[0].samples[0]["provider_object_id"].endswith("step-a")
