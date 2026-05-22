"""Tests for the Zepp data-API fetchers — H-fetch.

The fetchers are pure HTTP helpers; tests inject a recording
``HttpClient`` double that returns synthetic Zepp-shaped responses.
The shapes mirror what the H-revise probe captured on 2026-05-22
(see ``tests/fixtures/zepp/data-*-shape.json``) — minimal enough to
keep tests fast, faithful enough to catch a regression on the live
wire shape.

Coverage:

  * Each of the 6 fetchers issues the expected URL + params +
    headers.
  * ``apptoken`` + ``appname`` + ``appplatform`` + ``x-request-id``
    + ``r=<uuid>`` propagate correctly.
  * Base URL comes from ``token.metadata['base_url']`` — never
    hard-coded.
  * ``user_id`` comes from ``token.metadata['user_id']`` — REST
    paths embed it via str.format.
  * datetime / int → ms conversion happens once, on the way out.
  * ``date`` / ISO-string day conversion handles both.
  * Non-200 + non-JSON both raise :class:`AmazfitFetchError`.
  * ``token.metadata`` missing required keys raises early.
  * ``r=`` UUID is generated per-call (two consecutive calls get
    different UUIDs).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402

from plugins.sources.amazfit.fetch import (  # noqa: E402
    AmazfitFetchError,
    fetch_band_data,
    fetch_heart_rate,
    fetch_spo2_events,
    fetch_sport_load,
    fetch_stress_events,
    fetch_user_info,
)


@dataclass
class _FakeResponse:
    status_code: int
    payload: dict[str, Any] | None = None
    text: str = ""
    _raise_on_json: bool = False

    def json(self) -> dict[str, Any]:
        if self._raise_on_json:
            raise ValueError("not json")
        return self.payload or {}


@dataclass
class _RecordingHttpClient:
    responses: list[_FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url, *, params=None, headers=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        if not self.responses:
            raise AssertionError("no more canned responses queued")
        return self.responses.pop(0)


def _token(user_id: str = "3311629755", region: str = "us") -> OAuthToken:
    base_url = {
        "us": "https://api-mifit-us3.zepp.com",
        "eu": "https://api-mifit-de.zepp.com",
        "cn": "https://api-mifit.zepp.com",
    }[region]
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider="amazfit",
        access_token="TEST_APP_TOKEN",
        refresh_token=None,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        scopes=(),
        metadata={"base_url": base_url, "region": region, "user_id": user_id},
    )


def _assert_required_headers(
    call: dict[str, Any], expected_apptoken: str = "TEST_APP_TOKEN"
) -> None:
    headers = call["headers"]
    assert headers["apptoken"] == expected_apptoken
    assert headers["appname"] == "com.huami.midong"
    assert headers["appplatform"] == "ios_phone"
    # x-request-id is a UUID
    UUID(headers["x-request-id"])
    # r in params is also a UUID
    UUID(str(call["params"]["r"]))


# ─── fetch_user_info ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_user_info_hits_expected_url_and_params():
    http = _RecordingHttpClient([_FakeResponse(200, {"code": 1, "data": {}, "message": "ok"})])
    payload = await fetch_user_info(http, token=_token())
    assert payload == {"code": 1, "data": {}, "message": "ok"}
    [call] = http.calls
    assert call["url"] == "https://api-mifit-us3.zepp.com/huami.health.getUserInfo.json"
    assert call["params"]["userid"] == "3311629755"
    _assert_required_headers(call)


# ─── fetch_heart_rate ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_heart_rate_passes_user_id_in_path_and_ms_range():
    http = _RecordingHttpClient([_FakeResponse(200, {"items": []})])
    from_dt = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    to_dt = datetime(2026, 5, 22, 0, 0, tzinfo=UTC)
    payload = await fetch_heart_rate(http, token=_token(), from_time=from_dt, to_time=to_dt)
    assert payload == {"items": []}
    [call] = http.calls
    assert call["url"] == "https://api-mifit-us3.zepp.com/users/3311629755/heartRate"
    # Compute expected ms ranges dynamically so the assertion is robust
    # across leap-year arithmetic mistakes and TZ surprises.
    assert call["params"]["startTime"] == int(from_dt.timestamp() * 1000)
    assert call["params"]["endTime"] == int(to_dt.timestamp() * 1000)
    # And specifically the to-from delta equals 24h in ms.
    assert call["params"]["endTime"] - call["params"]["startTime"] == 86_400_000
    assert call["params"]["limit"] == 1000
    assert call["params"]["type"] == 2
    _assert_required_headers(call)


@pytest.mark.asyncio
async def test_fetch_heart_rate_accepts_already_ms_ints():
    http = _RecordingHttpClient([_FakeResponse(200, {"items": []})])
    await fetch_heart_rate(http, token=_token(), from_time=12345, to_time=67890, limit=500)
    [call] = http.calls
    assert call["params"]["startTime"] == 12345
    assert call["params"]["endTime"] == 67890
    assert call["params"]["limit"] == 500


# ─── fetch_band_data ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_band_data_defaults_to_summary():
    http = _RecordingHttpClient([_FakeResponse(200, {"code": 1, "data": {}, "message": "success"})])
    await fetch_band_data(http, token=_token(), day=date(2026, 5, 21))
    [call] = http.calls
    assert call["url"] == "https://api-mifit-us3.zepp.com/v1/data/band_data.json"
    assert call["params"]["from_date"] == "2026-05-21"
    assert call["params"]["to_date"] == "2026-05-21"
    assert call["params"]["query_type"] == "summary"
    assert call["params"]["byteLength"] == 8
    assert call["params"]["device_type"] == 0
    assert call["params"]["userid"] == "3311629755"


@pytest.mark.asyncio
async def test_fetch_band_data_accepts_iso_string_day():
    http = _RecordingHttpClient([_FakeResponse(200, {"data": {}})])
    await fetch_band_data(http, token=_token(), day="2026-05-21")
    [call] = http.calls
    assert call["params"]["from_date"] == "2026-05-21"


# ─── fetch_spo2_events / fetch_stress_events ────────────────────────────


@pytest.mark.asyncio
async def test_fetch_spo2_events_uses_correct_event_type_and_subtype():
    http = _RecordingHttpClient([_FakeResponse(200, {"items": []})])
    from_dt = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    to_dt = datetime(2026, 5, 22, 0, 0, tzinfo=UTC)
    await fetch_spo2_events(http, token=_token(), from_time=from_dt, to_time=to_dt)
    [call] = http.calls
    assert call["url"] == "https://api-mifit-us3.zepp.com/users/3311629755/events"
    assert call["params"]["eventType"] == "blood_oxygen"
    assert call["params"]["subType"] == "click"
    assert call["params"]["userId"] == "3311629755"
    assert call["params"]["reverse"] == "false"
    _assert_required_headers(call)


@pytest.mark.asyncio
async def test_fetch_stress_events_uses_correct_event_type_and_no_subtype():
    http = _RecordingHttpClient([_FakeResponse(200, {"items": []})])
    await fetch_stress_events(
        http,
        token=_token(),
        from_time=datetime(2026, 5, 21, tzinfo=UTC),
        to_time=datetime(2026, 5, 22, tzinfo=UTC),
    )
    [call] = http.calls
    assert call["params"]["eventType"] == "all_day_stress"
    # stress flow does not send a subType
    assert "subType" not in call["params"]


# ─── fetch_sport_load ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_sport_load_uses_iso_day_range_and_reverse_flag():
    http = _RecordingHttpClient([_FakeResponse(200, {"items": []})])
    await fetch_sport_load(
        http,
        token=_token(),
        start_day=date(2026, 5, 20),
        end_day=date(2026, 5, 22),
    )
    [call] = http.calls
    assert call["url"] == (
        "https://api-mifit-us3.zepp.com/v2/watch/users/3311629755/WatchSportStatistics/SPORT_LOAD"
    )
    assert call["params"]["startDay"] == "2026-05-20"
    assert call["params"]["endDay"] == "2026-05-22"
    assert call["params"]["limit"] == 900
    assert call["params"]["isReverse"] == "true"


# ─── base_url + user_id come from token metadata ───────────────────────


@pytest.mark.asyncio
async def test_fetch_uses_base_url_from_token_metadata_not_hardcoded():
    http = _RecordingHttpClient([_FakeResponse(200, {"code": 1, "data": {}, "message": "ok"})])
    await fetch_user_info(http, token=_token(region="eu"))
    [call] = http.calls
    assert call["url"].startswith("https://api-mifit-de.zepp.com")


@pytest.mark.asyncio
async def test_fetch_raises_when_token_metadata_missing_base_url():
    http = _RecordingHttpClient([])
    bad_token = OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider="amazfit",
        access_token="X",
        refresh_token=None,
        expires_at=None,
        scopes=(),
        metadata={"user_id": "42"},  # no base_url
    )
    with pytest.raises(AmazfitFetchError) as exc:
        await fetch_user_info(http, token=bad_token)
    assert "base_url" in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_raises_when_token_metadata_missing_user_id():
    http = _RecordingHttpClient([])
    bad_token = OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider="amazfit",
        access_token="X",
        refresh_token=None,
        expires_at=None,
        scopes=(),
        metadata={"base_url": "https://api-mifit-us3.zepp.com"},  # no user_id
    )
    with pytest.raises(AmazfitFetchError) as exc:
        await fetch_user_info(http, token=bad_token)
    assert "user_id" in str(exc.value)


# ─── error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_non_200_raises_amazfit_fetch_error():
    http = _RecordingHttpClient([_FakeResponse(500, payload={}, text="boom")])
    with pytest.raises(AmazfitFetchError) as exc:
        await fetch_user_info(http, token=_token())
    assert "500" in str(exc.value)
    assert "boom" in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_non_json_raises_amazfit_fetch_error():
    http = _RecordingHttpClient([_FakeResponse(200, payload=None, _raise_on_json=True)])
    with pytest.raises(AmazfitFetchError):
        await fetch_user_info(http, token=_token())


# ─── r=<uuid> is generated per-call ─────────────────────────────────────


@pytest.mark.asyncio
async def test_r_query_param_changes_per_call():
    http = _RecordingHttpClient(
        [
            _FakeResponse(200, {"items": []}),
            _FakeResponse(200, {"items": []}),
        ]
    )
    await fetch_user_info(http, token=_token())
    await fetch_user_info(http, token=_token())
    r1 = http.calls[0]["params"]["r"]
    r2 = http.calls[1]["params"]["r"]
    assert r1 != r2
    UUID(r1)
    UUID(r2)


# ─── x-request-id is also per-call ──────────────────────────────────────


@pytest.mark.asyncio
async def test_x_request_id_changes_per_call():
    http = _RecordingHttpClient(
        [
            _FakeResponse(200, {"items": []}),
            _FakeResponse(200, {"items": []}),
        ]
    )
    await fetch_user_info(http, token=_token())
    await fetch_user_info(http, token=_token())
    xrid1 = http.calls[0]["headers"]["x-request-id"]
    xrid2 = http.calls[1]["headers"]["x-request-id"]
    assert xrid1 != xrid2


# ─── anti: no hardcoded .huami.com hosts in fetch.py source ────────────


def test_fetch_source_does_not_contain_deprecated_huami_com_hosts():
    """H-revise migrated the data API from api-mifit-us2.huami.com to
    api-mifit-us3.zepp.com. If a future edit reverts that, this test
    catches it. (.zepp.com is allowed in docstrings as a reference;
    only .huami.com is the failure marker.)
    """
    fetch_source = (ROOT / "plugins" / "sources" / "amazfit" / "fetch.py").read_text()
    assert "huami.com" not in fetch_source, "fetch.py must not contain .huami.com hosts"


def test_fetch_source_does_not_hardcode_a_full_zepp_url():
    """fetch.py should derive base_url from token.metadata. A hardcoded
    ``https://api-mifit-us3.zepp.com`` literal in the runnable code
    would defeat region routing.
    """
    fetch_source = (ROOT / "plugins" / "sources" / "amazfit" / "fetch.py").read_text()
    # Strip docstrings so a comment / docstring reference does not trip
    # the assertion.
    import re

    code_only = re.sub(r'"""[\s\S]*?"""', "", fetch_source)
    code_only = re.sub(r"'''[\s\S]*?'''", "", code_only)
    assert "https://api-mifit" not in code_only, (
        "fetch.py code (excluding docstrings) must not contain a hardcoded api-mifit URL; "
        "derive base_url from token.metadata."
    )
