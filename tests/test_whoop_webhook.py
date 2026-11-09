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


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


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

    session = _Session()
    result = await _plugin().handle_webhook(
        {
            "event": {"type": "recovery.updated", "id": "rec-1"},
            "storage": storage,
            "session": session,
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    # The rotated token is committed before the fetch, on its own.
    assert session.commits == 1
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


# ── Deletions, vanished resources, and failure classification (M13) ────────


class _CanonicalRepo:
    def __init__(self, superseded: int = 1) -> None:
        self.calls: list[dict[str, Any]] = []
        self._superseded = superseded

    async def supersede_source_records(self, session, **kwargs):
        self.calls.append(kwargs)
        return self._superseded


@pytest.mark.asyncio
async def test_a_deleted_workout_is_superseded_without_fetching_it():
    http = _HttpClient()  # any GET would raise: the resource is gone
    canonical = _CanonicalRepo()

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "workout.deleted", "id": "wk-9"},
            "storage": _RecordingStorage(),
            "session": object(),
            "http_client": http,
            "token_store": _TokenStore(initial_token=_fresh_token()),
            "canonical_repository": canonical,
        }
    )

    assert result == {"accepted": 0, "rejected": 0, "deleted": 1}
    assert http.get_calls == []
    assert canonical.calls == [
        {
            "owner_id": DEFAULT_OWNER_ID,
            "normalizer_id": "whoop-healthsave",
            "source_record_uids": ["wk-9"],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["sleep.deleted", "recovery.deleted"])
async def test_a_deleted_sleep_or_recovery_is_acknowledged_without_fetching(event_type):
    http = _HttpClient()
    canonical = _CanonicalRepo()

    result = await _plugin().handle_webhook(
        {
            "event": {"type": event_type, "id": "res-9"},
            "storage": _RecordingStorage(),
            "session": object(),
            "http_client": http,
            "token_store": _TokenStore(initial_token=_fresh_token()),
            "canonical_repository": canonical,
        }
    )

    assert result == {"accepted": 0, "rejected": 0, "deleted": 0}
    assert http.get_calls == []
    assert canonical.calls == []


@pytest.mark.asyncio
async def test_an_updated_resource_that_is_gone_is_acknowledged_not_failed():
    storage = _RecordingStorage()
    http = _HttpClient(get_responses={PATH_SLEEP: _Response(404, {"message": "not found"})})

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "sleep.updated", "id": "slp-9"},
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": _TokenStore(initial_token=_fresh_token()),
        }
    )

    assert result == {"accepted": 0, "rejected": 0, "missing": 1}
    assert storage.ingest_calls == []


def _route_client(monkeypatch, failure: BaseException):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.api import v2_sources
    from server.api.deps import get_session

    class _RouteSession:
        def __init__(self) -> None:
            self.rollbacks = 0

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            self.rollbacks += 1

    async def failing(self, payload):
        raise failure

    monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(WhoopSource, "handle_webhook", failing)
    app = FastAPI()
    app.include_router(v2_sources.router)
    session = _RouteSession()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app, raise_server_exceptions=False), session


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        ("fetch-400", 422),
        ("fetch-403", 422),
        ("fetch-500", 503),
        ("fetch-429", 503),
        ("oauth-400", 422),
        ("oauth-503", 503),
        ("connect", 503),
        ("data-error", 422),
        ("key-error", 422),
    ],
)
def test_the_webhook_route_answers_deterministic_failures_with_422_never_500(
    monkeypatch, failure, status
):
    import httpx
    from sqlalchemy.exc import DataError

    from plugins.sources.whoop.fetch import WhoopFetchError
    from plugins.sources.whoop.oauth import WhoopOAuthError

    exc = {
        "fetch-400": WhoopFetchError("HTTP 400", status_code=400),
        "fetch-403": WhoopFetchError("HTTP 403", status_code=403),
        "fetch-500": WhoopFetchError("HTTP 500", status_code=500),
        "fetch-429": WhoopFetchError("HTTP 429", status_code=429),
        "oauth-400": WhoopOAuthError("HTTP 400: invalid_grant", status_code=400),
        "oauth-503": WhoopOAuthError("HTTP 503", status_code=503),
        "connect": httpx.ConnectError("refused"),
        "data-error": DataError("INSERT", {}, Exception("value out of range")),
        "key-error": KeyError("score"),
    }[failure]
    client, session = _route_client(monkeypatch, exc)

    response = client.post("/api/v2/sources/whoop/webhook", json={"type": "x.updated", "id": "1"})

    assert response.status_code == status
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_a_webhook_fetch_refused_with_401_refreshes_once_and_ingests():
    class _Http(_HttpClient):
        async def get(self, url, *, params=None, headers=None):
            if (headers or {}).get("Authorization") == "Bearer AT-fresh":
                self.get_calls.append({"url": url, "params": {}})
                return _Response(401, {"message": "Authorization was not valid"})
            return await super().get(url, params=params, headers=headers)

    http = _Http(
        get_responses={PATH_WORKOUT: _Response(200, _WORKOUT_RECORD)},
        post_responses={
            "oauth2/token": _Response(
                200,
                {
                    "access_token": "AT-new",
                    "refresh_token": "RT-new",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        },
    )
    token_store = _TokenStore(initial_token=_fresh_token())

    result = await _plugin().handle_webhook(
        {
            "event": {"type": "workout.updated", "id": "wk-1"},
            "storage": _RecordingStorage(),
            "session": _Session(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert [kind for _, kind in token_store.put_calls] == ["refreshed"]
