"""End-to-end tests for ``WhoopSource.ingest``.

Tests inject a recording IngestStorage, a fake token store, and a
recording HTTP client. They cover:

  * Happy path: fresh token, four fetches, normalization, per-metric
    writes via storage.ingest_metric.
  * Expired token: refresh_access_token called, put_token('refreshed')
    audited, ingest proceeds with the new access_token.
  * Refresh failure: record_refresh_failure audited, exception re-raised.
  * Expired token with no refresh_token stored: WhoopOAuthError raised
    + audit event recorded.
  * Empty data: returns {"accepted": 0, "rejected": 0} without crashing.
"""

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
from plugins.sources.whoop.fetch import (  # noqa: E402
    PATH_CYCLE,
    PATH_RECOVERY,
    PATH_SLEEP,
    PATH_WORKOUT,
)
from plugins.sources.whoop.oauth import WhoopClientConfig, WhoopOAuthError  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "whoop"


# ──────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _HttpClient:
    """Records every GET / POST; serves canned responses per URL contains-match."""

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
    """IngestStorage Protocol impl that records ingest_metric calls."""

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
    """In-memory token store mimicking the storage.timescale.oauth_tokens module."""

    initial_token: OAuthToken | None = None
    put_calls: list[tuple[OAuthToken, str]] = field(default_factory=list)
    refresh_failures: list[str] = field(default_factory=list)

    async def get_token(self, session, *, provider, owner_id):
        return self.initial_token

    async def put_token(self, session, token, *, event_kind="authorized"):
        self.put_calls.append((token, event_kind))
        # Persist the new token so subsequent get_token calls would see it.
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


# Synthetic Whoop payloads — minimal, just enough that normalize_*
# emits at least one sample so we can assert storage routing.
_RECOVERY_RECORDS = [
    {
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
]
_SLEEP_RECORDS = [
    {
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
]
_WORKOUT_RECORDS = [
    {
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
]
_CYCLE_RECORDS = [
    {
        "id": 1,
        "created_at": "2026-05-22T08:00:00Z",
        "score_state": "SCORED",
        "score": {"strain": 8.5, "average_heart_rate": 75},
    }
]


def _default_get_responses(
    *,
    recovery=None,
    sleep=None,
    workout=None,
    cycle=None,
) -> dict[str, _Response]:
    return {
        PATH_RECOVERY: _Response(
            200, {"records": recovery if recovery is not None else _RECOVERY_RECORDS}
        ),
        PATH_SLEEP: _Response(200, {"records": sleep if sleep is not None else _SLEEP_RECORDS}),
        PATH_WORKOUT: _Response(
            200, {"records": workout if workout is not None else _WORKOUT_RECORDS}
        ),
        PATH_CYCLE: _Response(200, {"records": cycle if cycle is not None else _CYCLE_RECORDS}),
    }


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_happy_path_with_fresh_token():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient(get_responses=_default_get_responses())
    plugin = WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))

    result = await plugin.ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    assert result["rejected"] == 0

    # No refresh expected when the token is fresh.
    assert http.post_calls == []
    assert token_store.put_calls == []

    # One device write registers "Whoop".
    assert storage.devices == {"Whoop": 1}

    # Each fetch hits the right Whoop path with a Bearer header.
    paths_hit = [c["url"] for c in http.get_calls]
    assert any(PATH_RECOVERY in u for u in paths_hit)
    assert any(PATH_SLEEP in u for u in paths_hit)
    assert any(PATH_WORKOUT in u for u in paths_hit)
    assert any(PATH_CYCLE in u for u in paths_hit)

    # All ingest_metric calls share the Whoop device_id.
    assert {c.device_id for c in storage.ingest_calls} == {1}
    # The recorded metrics include the ones normalize_* emits.
    written_metrics = {c.metric for c in storage.ingest_calls}
    assert "heart_rate_variability" in written_metrics
    assert "blood_oxygen" in written_metrics
    assert "workouts" in written_metrics
    assert "strain" in written_metrics


@pytest.mark.asyncio
async def test_ingest_refreshes_expired_token_and_audits_refreshed_event():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_expired_token())

    refresh_response = _Response(
        200,
        {
            "access_token": "AT-new",
            "refresh_token": "RT-new",
            "expires_in": 3600,
            "scope": "read:recovery offline",
            "token_type": "Bearer",
        },
    )
    http = _HttpClient(
        get_responses=_default_get_responses(),
        post_responses={"oauth2/token": refresh_response},
    )
    plugin = WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))

    result = await plugin.ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )

    assert result["accepted"] > 0
    # Refresh happened
    assert len(http.post_calls) == 1
    assert http.post_calls[0]["data"]["grant_type"] == "refresh_token"
    assert http.post_calls[0]["data"]["refresh_token"] == "RT-expired"
    # Audit: refreshed
    assert len(token_store.put_calls) == 1
    assert token_store.put_calls[0][1] == "refreshed"
    assert token_store.put_calls[0][0].access_token == "AT-new"
    # Subsequent fetches use the new access token in the Authorization header.
    # We assert the header indirectly: the new token survived the refresh and
    # is now the stored initial_token.
    assert token_store.initial_token is not None
    assert token_store.initial_token.access_token == "AT-new"


@pytest.mark.asyncio
async def test_ingest_records_refresh_failure_and_reraises():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_expired_token())

    refresh_response = _Response(401, {"error": "invalid_grant"}, text="nope")
    http = _HttpClient(
        get_responses=_default_get_responses(),
        post_responses={"oauth2/token": refresh_response},
    )
    plugin = WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))

    with pytest.raises(WhoopOAuthError):
        await plugin.ingest(
            {
                "storage": storage,
                "session": object(),
                "http_client": http,
                "token_store": token_store,
                "oauth_config": _oauth_config(),
            }
        )

    assert len(token_store.refresh_failures) == 1
    assert "401" in token_store.refresh_failures[0] or "HTTP" in token_store.refresh_failures[0]
    # No metric writes when refresh failed.
    assert storage.ingest_calls == []


@pytest.mark.asyncio
async def test_ingest_expired_token_with_no_refresh_token_audits_and_raises():
    storage = _RecordingStorage()
    token_no_refresh = OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=PROVIDER,
        access_token="AT-expired",
        refresh_token=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    token_store = _TokenStore(initial_token=token_no_refresh)
    http = _HttpClient(get_responses=_default_get_responses())
    plugin = WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))

    with pytest.raises(WhoopOAuthError):
        await plugin.ingest(
            {
                "storage": storage,
                "session": object(),
                "http_client": http,
                "token_store": token_store,
                "oauth_config": _oauth_config(),
            }
        )
    assert len(token_store.refresh_failures) == 1
    assert "refresh_token" in token_store.refresh_failures[0]


@pytest.mark.asyncio
async def test_ingest_with_empty_data_returns_zero():
    storage = _RecordingStorage()
    token_store = _TokenStore(initial_token=_fresh_token())
    http = _HttpClient(
        get_responses=_default_get_responses(recovery=[], sleep=[], workout=[], cycle=[])
    )
    plugin = WhoopSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))

    result = await plugin.ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
            "oauth_config": _oauth_config(),
        }
    )
    assert result == {"accepted": 0, "rejected": 0}
    # Device still gets created (call shape consistency); no metric writes.
    assert storage.devices == {"Whoop": 1}
    assert storage.ingest_calls == []
