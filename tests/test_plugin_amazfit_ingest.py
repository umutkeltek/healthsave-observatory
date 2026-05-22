"""End-to-end tests for ``AmazfitSource.ingest`` — H-ingest.

Tests inject a recording IngestStorage, a fake token store, and a
recording HTTP client. Cover:

  * Happy path: fresh token, five fetches, normalization, per-metric
    writes via storage.ingest_metric. Verifies source_id propagation.
  * Expired token: record_refresh_failure audited, AmazfitAuthError
    raised. Confirms NO re-login attempt (no refresh primitive).
  * No token stored: returns {"accepted": 0, "rejected": 0}.
  * Empty payloads from all 5 endpoints: no writes, no crash.
  * Fetcher non-200: AmazfitFetchError surfaces (worker's
    pipeline_runs ledger picks it up).
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402
from plugin_sdk import load_manifest  # noqa: E402

from plugins.sources.amazfit import PROVIDER, AmazfitSource  # noqa: E402
from plugins.sources.amazfit.auth import AmazfitAuthError  # noqa: E402

PLUGIN_DIR = ROOT / "plugins" / "sources" / "amazfit"


# ──────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any] | None = None
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload or {}


@dataclass
class _HttpClient:
    """Returns canned responses per URL contains-match. Records every GET.

    Match algorithm:
      1. If the needle starts with ``events:<eventType>``, the URL must
         contain ``/events`` AND the params must have a matching
         ``eventType`` key. Lets us serve different fixtures for the
         spo2 and stress calls that both hit /users/<id>/events.
      2. Otherwise plain substring match against the URL.
    """

    responses: dict[str, _Response] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url, *, params=None, headers=None):
        params = dict(params or {})
        self.calls.append({"url": url, "params": params, "headers": dict(headers or {})})
        for needle, response in self.responses.items():
            if needle.startswith("events:"):
                want = needle[len("events:") :]
                if "/events" in url and params.get("eventType") == want:
                    return response
            elif needle in url:
                return response
        raise AssertionError(f"no canned response for url={url} params={params}")


@dataclass
class _RecordingStorage:
    """Records every get_or_create_device + ingest_metric call."""

    device_id: int = 42
    accept_counts: dict[str, int] = field(default_factory=dict)
    device_calls: list[dict[str, Any]] = field(default_factory=list)
    ingest_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_or_create_device(self, session, device_type):
        self.device_calls.append({"device_type": device_type})
        return self.device_id

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        self.ingest_calls.append(
            {
                "device_id": device_id,
                "metric": metric,
                "samples": samples,
                "owner_id": owner_id,
            }
        )
        return self.accept_counts.get(metric, len(samples))


@dataclass
class _TokenStore:
    """Recording token store."""

    token: OAuthToken | None = None
    put_calls: list[dict[str, Any]] = field(default_factory=list)
    refresh_failure_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_token(self, session, *, provider, owner_id):
        return self.token

    async def put_token(self, session, new_token, *, event_kind=None):
        self.put_calls.append({"token": new_token, "event_kind": event_kind})

    async def record_refresh_failure(self, session, *, provider, owner_id, error_message):
        self.refresh_failure_calls.append(
            {"provider": provider, "owner_id": owner_id, "error_message": error_message}
        )


def _token(*, expired: bool = False) -> OAuthToken:
    expires_at = (
        datetime.now(UTC) - timedelta(hours=1)
        if expired
        else datetime.now(UTC) + timedelta(days=10)
    )
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=PROVIDER,
        access_token="TEST_TOKEN_VALUE",
        refresh_token=None,
        expires_at=expires_at,
        scopes=(),
        metadata={
            "base_url": "https://api-mifit-us3.zepp.com",
            "region": "us",
            "user_id": "99999999",
        },
    )


def _band_data_b64(summary_obj: dict, date_str: str = "2026-05-21") -> dict:
    encoded = base64.b64encode(json.dumps(summary_obj).encode("utf-8")).decode("ascii")
    return {
        "code": 1,
        "message": "success",
        "data": [
            {
                "uid": "99999999",
                "data_type": 0,
                "date_time": date_str,
                "summary": encoded,
                "device_id": "2445B531000074",
            }
        ],
    }


def _plugin() -> AmazfitSource:
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    return AmazfitSource(manifest)


def _ok_responses() -> dict[str, _Response]:
    """Canned 200 responses for all 5 fetched endpoints."""
    return {
        "/users/99999999/heartRate": _Response(
            200, {"items": [{"time": 1779408000000, "value": 72}]}
        ),
        # SpO2 + stress both hit /users/<id>/events — disambiguate via
        # the eventType params key (see _HttpClient match algorithm).
        "events:blood_oxygen": _Response(
            200,
            {
                "items": [
                    {
                        "eventType": "blood_oxygen",
                        "extra": json.dumps({"spo2": 99}),
                        "subType": "click",
                        "timestamp": 1779408000000,
                    }
                ]
            },
        ),
        "events:all_day_stress": _Response(
            200,
            {
                "items": [
                    {
                        "eventType": "all_day_stress",
                        "avgStress": "24",
                        "data": json.dumps([{"time": 1779408000000, "value": 30}]),
                    }
                ]
            },
        ),
        "/v1/data/band_data.json": _Response(
            200,
            _band_data_b64(
                {
                    "stp": {"ttl": 3786, "dis": 2772, "cal": 156},
                    "slp": {"st": 29657115, "ed": 29657580, "dp": 120, "lb": 240, "wk": 30},
                    "hr": {"maxHr": {"hr": 142, "ts": 1779408000}},
                }
            ),
        ),
        "WatchSportStatistics/SPORT_LOAD": _Response(
            200, {"items": [{"dayId": "20260521", "wtlSum": 145}]}
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_no_token_returns_zero_counts():
    storage = _RecordingStorage()
    http = _HttpClient()
    token_store = _TokenStore(token=None)
    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    assert result == {"accepted": 0, "rejected": 0}
    assert http.calls == []
    assert storage.ingest_calls == []


@pytest.mark.asyncio
async def test_ingest_expired_token_raises_and_records_failure():
    storage = _RecordingStorage()
    http = _HttpClient()
    token_store = _TokenStore(token=_token(expired=True))
    with pytest.raises(AmazfitAuthError) as exc:
        await _plugin().ingest(
            {
                "storage": storage,
                "session": object(),
                "http_client": http,
                "token_store": token_store,
            }
        )
    assert "expired" in str(exc.value).lower()
    assert "huami-token" in str(exc.value)
    assert "re-extract" in str(exc.value)
    assert len(token_store.refresh_failure_calls) == 1
    assert token_store.refresh_failure_calls[0]["provider"] == PROVIDER
    assert http.calls == []  # never touched the network


@pytest.mark.asyncio
async def test_ingest_happy_path_writes_per_metric_with_amazfit_source_tag():
    storage = _RecordingStorage()
    http = _HttpClient(responses=_ok_responses())
    token_store = _TokenStore(token=_token())
    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    # We accept whatever the storage counts return; what matters here
    # is the routing.
    assert result["rejected"] == 0
    assert result["accepted"] >= 1

    # All 5 fetcher endpoints were hit.
    urls_hit = [c["url"] for c in http.calls]
    assert any("/users/99999999/heartRate" in u for u in urls_hit)
    assert any("/v1/data/band_data.json" in u for u in urls_hit)
    assert any("/users/99999999/events" in u for u in urls_hit)
    assert any("WatchSportStatistics/SPORT_LOAD" in u for u in urls_hit)

    # Device label is "Amazfit"
    assert storage.device_calls == [{"device_type": "Amazfit"}]

    # Every ingest_metric call carried source="Amazfit" in its samples.
    assert storage.ingest_calls, "expected at least one ingest_metric call"
    for call in storage.ingest_calls:
        for sample in call["samples"]:
            assert sample["source"].startswith("Amazfit"), (
                f"metric={call['metric']} sample={sample} missing Amazfit source tag"
            )


@pytest.mark.asyncio
async def test_ingest_routes_blood_oxygen_metric_from_spo2_events():
    storage = _RecordingStorage()
    http = _HttpClient(responses=_ok_responses())
    token_store = _TokenStore(token=_token())
    await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    metrics_written = {c["metric"] for c in storage.ingest_calls}
    assert "blood_oxygen" in metrics_written


@pytest.mark.asyncio
async def test_ingest_routes_daily_activity_and_sleep_from_band_data():
    storage = _RecordingStorage()
    http = _HttpClient(responses=_ok_responses())
    token_store = _TokenStore(token=_token())
    await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    metrics_written = {c["metric"] for c in storage.ingest_calls}
    assert "daily_activity" in metrics_written
    assert "sleep_analysis" in metrics_written
    assert "heart_rate" in metrics_written  # includes daily-max sample


@pytest.mark.asyncio
async def test_ingest_routes_training_load_from_sport_load():
    storage = _RecordingStorage()
    http = _HttpClient(responses=_ok_responses())
    token_store = _TokenStore(token=_token())
    await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    metrics_written = {c["metric"] for c in storage.ingest_calls}
    assert "training_load" in metrics_written


@pytest.mark.asyncio
async def test_ingest_all_empty_payloads_returns_zero_counts_without_crashing():
    storage = _RecordingStorage()
    http = _HttpClient(
        responses={
            "/heartRate": _Response(200, {"items": []}),
            "events:blood_oxygen": _Response(200, {"items": []}),
            "events:all_day_stress": _Response(200, {"items": []}),
            "/v1/data/band_data.json": _Response(200, {"code": 1, "message": "ok", "data": []}),
            "WatchSportStatistics/SPORT_LOAD": _Response(200, {"items": []}),
        }
    )
    token_store = _TokenStore(token=_token())
    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": token_store,
        }
    )
    assert result == {"accepted": 0, "rejected": 0}
    # No metrics had samples → no ingest_metric calls at all.
    assert storage.ingest_calls == []


@pytest.mark.asyncio
async def test_ingest_propagates_fetcher_non_200_as_amazfit_fetch_error():
    from plugins.sources.amazfit.fetch import AmazfitFetchError

    storage = _RecordingStorage()
    http = _HttpClient(
        responses={
            "/heartRate": _Response(503, payload={}, text="upstream error"),
            "events:blood_oxygen": _Response(200, {"items": []}),
            "events:all_day_stress": _Response(200, {"items": []}),
            "/v1/data/band_data.json": _Response(200, {"data": []}),
            "WatchSportStatistics/SPORT_LOAD": _Response(200, {"items": []}),
        }
    )
    token_store = _TokenStore(token=_token())
    with pytest.raises(AmazfitFetchError):
        await _plugin().ingest(
            {
                "storage": storage,
                "session": object(),
                "http_client": http,
                "token_store": token_store,
            }
        )


@pytest.mark.asyncio
async def test_ingest_no_login_attempted_on_expired_token():
    """Anti-regression: H-revise specifically removed login() from this
    plugin. Verify the ingest path never tries to call into auth.login
    on token expiry.
    """
    from plugins.sources.amazfit import auth as auth_mod

    assert not hasattr(auth_mod, "login")
    assert not hasattr(auth_mod, "md5_password")
