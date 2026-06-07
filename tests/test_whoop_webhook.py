"""Webhook-focused tests for ``WhoopSource.handle_webhook``."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402
from plugin_sdk import load_manifest  # noqa: E402

from plugins.sources.whoop import PROVIDER, WhoopSource  # noqa: E402
from plugins.sources.whoop.fetch import PATH_RECOVERY, PATH_SLEEP, PATH_WORKOUT  # noqa: E402
from plugins.sources.whoop.oauth import WhoopClientConfig  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "whoop"


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _HttpClient:
    def __init__(
        self,
        *,
        get_responses: dict[str, _Response] | None = None,
        post_responses: dict[str, _Response] | None = None,
    ) -> None:
        self._gets = get_responses or {}
        self._posts = post_responses or {}
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    async def get(self, url, *, params=None, headers=None):
        self.get_calls.append({"url": url, "params": dict(params or {})})
        for needle, response in self._gets.items():
            if needle in url:
                return response
        raise AssertionError(f"no canned GET response for url={url}")

    async def post(self, url, *, data=None, headers=None):
        self.post_calls.append({"url": url, "data": dict(data or {})})
        for needle, response in self._posts.items():
            if needle in url:
                return response
        raise AssertionError(f"no canned POST response for url={url}")


@dataclass
class _IngestCall:
    metric: str
    samples: list[dict[str, Any]]
    device_id: int | str
    owner_id: UUID


class _RecordingStorage:
    def __init__(self) -> None:
        self.devices: dict[str, int] = {}
        self.next_device_id = 1
        self.ingest_calls: list[_IngestCall] = []

    async def get_or_create_device(self, session, device_type):
        if device_type not in self.devices:
            self.devices[device_type] = self.next_device_id
            self.next_device_id += 1
        return self.devices[device_type]

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        self.ingest_calls.append(
            _IngestCall(metric=metric, samples=samples, device_id=device_id, owner_id=owner_id)
        )
        return len(samples)


@dataclass
class _TokenStore:
    initial_token: OAuthToken | None = None
    put_calls: list[tuple[OAuthToken, str]] = field(default_factory=list)
    refresh_failures: list[str] = field(default_factory=list)

    async def get_token(self, session, *, provider, owner_id):
        return self.initial_token

    async def put_token(self, session, token, *, event_kind="authorized"):
        self.put_calls.append((token, event_kind))
        self.initial_token = token

    async def record_refresh_failure(
        self, session, *, provider, error_message, owner_id=DEFAULT_OWNER_ID
    ):
        self.refresh_failures.append(error_message)


def _fresh_token() -> OAuthToken:
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=PROVIDER,
        access_token="AT-fresh",
        refresh_token="RT-fresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("read:recovery", "offline"),
    )


def _expired_token() -> OAuthToken:
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=PROVIDER,
        access_token="AT-expired",
        refresh_token="RT-expired",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        scopes=("read:recovery", "offline"),
    )


def _oauth_config() -> WhoopClientConfig:
    return WhoopClientConfig(client_id="cid", client_secret="csecret", redirect_uri="https://t/cb")


_RECOVERY_RECORD = {
    "cycle_id": 1,
    "created_at": "2026-05-22T08:00:00Z",
    "score_state": "SCORED",
    "score": {
        "recovery_score": 73,
        "resting_heart_rate": 58,
        "hrv_rmssd_milli": 64.3,
        "spo2_percentage": 97.0,
        "skin_temp_celsius": 35.2,
    },
}
_SLEEP_RECORD = {
    "id": 1,
    "start": "2026-05-22T00:30:00Z",
    "end": "2026-05-22T08:00:00Z",
    "score_state": "SCORED",
    "score": {
        "stage_summary": {
            "total_in_bed_time_milli": 27_000_000,
            "total_awake_time_milli": 1_800_000,
        },
        "sleep_efficiency_percentage": 96.5,
        "respiratory_rate": 16.8,
    },
}
_WORKOUT_RECORD = {
    "id": 1,
    "start": "2026-05-22T18:00:00Z",
    "end": "2026-05-22T18:45:00Z",
    "sport_id": 0,
    "score_state": "SCORED",
    "score": {
        "average_heart_rate": 145,
        "max_heart_rate": 178,
        "kilojoule": 1500.0,
    },
}


def _plugin() -> WhoopSource:
    return WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))


@pytest.mark.asyncio
async def test_handle_webhook_recovery_event_fetches_and_ingests():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient(get_responses={PATH_RECOVERY: _Response(200, _RECOVERY_RECORD)})

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "recovery.updated", "id": "rec-1"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert any(f"{PATH_RECOVERY}/rec-1" in call["url"] for call in http.get_calls)
    written_metrics = {call.metric for call in storage.ingest_calls}
    assert "heart_rate_variability" in written_metrics
    assert "blood_oxygen" in written_metrics


@pytest.mark.asyncio
async def test_handle_webhook_sleep_event_fetches_and_ingests():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient(get_responses={PATH_SLEEP: _Response(200, _SLEEP_RECORD)})

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "sleep.updated", "id": "slp-1"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert any(f"{PATH_SLEEP}/slp-1" in call["url"] for call in http.get_calls)
    written_metrics = {call.metric for call in storage.ingest_calls}
    assert "sleep_efficiency_percentage" in written_metrics
    assert "sleep_respiratory_rate" in written_metrics


@pytest.mark.asyncio
async def test_handle_webhook_workout_event_fetches_and_ingests():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient(get_responses={PATH_WORKOUT: _Response(200, _WORKOUT_RECORD)})

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "workout.updated", "id": "wk-1"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert any(f"{PATH_WORKOUT}/wk-1" in call["url"] for call in http.get_calls)
    written_metrics = {call.metric for call in storage.ingest_calls}
    assert "workouts" in written_metrics


@pytest.mark.asyncio
async def test_handle_webhook_unknown_event_type_is_noop():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient()

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "user.something", "id": "x"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result == {"accepted": 0, "rejected": 0}
    assert http.get_calls == []
    assert storage.ingest_calls == []


@pytest.mark.asyncio
async def test_handle_webhook_missing_type_or_id_raises_value_error():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient()

    with pytest.raises(ValueError, match="missing type/id"):
        await _plugin().handle_webhook(
            {
                "event": {},
                "storage": storage,
                "session": object(),
                "http_client": http,
                "token_store": token_store,
                "oauth_config": _oauth_config(),
            }
        )


@pytest.mark.asyncio
async def test_handle_webhook_refreshes_expired_token_then_ingests():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_expired_token())
    http = _HttpClient(
        get_responses={PATH_RECOVERY: _Response(200, _RECOVERY_RECORD)},
        post_responses={
            "oauth2/token": _Response(
                200,
                {
                    "access_token": "AT-new",
                    "refresh_token": "RT-new",
                    "expires_in": 3600,
                    "scope": "read:recovery offline",
                    "token_type": "Bearer",
                },
            )
        },
    )

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "recovery.updated", "id": "rec-1"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert len(http.post_calls) == 1
    assert http.post_calls[0]["data"]["grant_type"] == "refresh_token"
    assert len(token_store.put_calls) == 1
    assert token_store.put_calls[0][1] == "refreshed"


@pytest.mark.asyncio
async def test_handle_webhook_with_no_stored_token_is_noop():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=None)
    http = _HttpClient()

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "recovery.updated", "id": "rec-1"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result == {"accepted": 0, "rejected": 0}
    assert http.get_calls == []
