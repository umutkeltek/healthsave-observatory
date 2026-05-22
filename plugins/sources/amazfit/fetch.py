"""Zepp data-API fetchers — H-fetch implementation (2026-05-22).

Each fetcher hits a specific path on ``api-mifit-*.zepp.com``, with
the apptoken-style auth header and the per-call ``r=<uuid>`` query
parameter the live backend requires. Wire shapes were captured from
real traffic on 2026-05-22 against a valid huami-token-issued
``app_token``; fixtures live at ``tests/fixtures/zepp/data-*-shape.json``
and inform the test cases below.

Fetcher → endpoint map:

  * ``fetch_user_info``        → ``/huami.health.getUserInfo.json``
  * ``fetch_heart_rate``       → ``/users/<id>/heartRate``
  * ``fetch_band_data``        → ``/v1/data/band_data.json``
  * ``fetch_spo2_events``      → ``/users/<id>/events?eventType=blood_oxygen``
  * ``fetch_stress_events``    → ``/users/<id>/events?eventType=all_day_stress``
  * ``fetch_sport_load``       → ``/v2/watch/users/<id>/WatchSportStatistics/SPORT_LOAD``

The Zepp data API is single-page per call — there is no cursor /
``next_token`` pagination. Day-range filtering is the dimension that
limits payload size; callers iterate by day window themselves
(see :mod:`plugins.sources.amazfit` ``AmazfitSource.ingest`` in
H-ingest).

``HttpClient`` Protocol matches httpx.AsyncClient's GET surface so
tests inject a recording double without touching the network.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, date, datetime
from typing import Any, Protocol

from auth import OAuthToken

from . import DATA_API_HEADERS_BASE

# Path constants kept near the call sites so a search for a Zepp
# endpoint string lands at one obvious place.
PATH_USER_INFO = "/huami.health.getUserInfo.json"
PATH_HEART_RATE = "/users/{user_id}/heartRate"
PATH_BAND_DATA = "/v1/data/band_data.json"
PATH_EVENTS = "/users/{user_id}/events"
PATH_SPORT_LOAD = "/v2/watch/users/{user_id}/WatchSportStatistics/SPORT_LOAD"

# Default limits — the live API caps at 1000 for heart rate / events;
# 900 for SPORT_LOAD. We ask explicitly so a future cap change does
# not silently shrink our fetch.
DEFAULT_LIMIT = 1000
SPORT_LOAD_LIMIT = 900


class AmazfitFetchError(Exception):
    """Raised when a Zepp data endpoint returns non-200 or malformed JSON."""


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class HttpClient(Protocol):
    """Minimal GET surface so callers can pass an ``httpx.AsyncClient``
    or a test double interchangeably.
    """

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def _r() -> str:
    """Per-request UUID for the ``r=`` query param the API requires."""
    return str(_uuid.uuid4())


def _headers(token: OAuthToken) -> dict[str, str]:
    """Build the per-call header set: static base + apptoken + x-request-id."""
    return {
        **DATA_API_HEADERS_BASE,
        "apptoken": token.access_token,
        "x-request-id": str(_uuid.uuid4()),
    }


def _require_metadata(token: OAuthToken, *keys: str) -> dict[str, str]:
    """Extract required ``metadata`` keys or raise with a clear message."""
    missing = [k for k in keys if not (token.metadata or {}).get(k)]
    if missing:
        raise AmazfitFetchError(f"token metadata missing required keys: {', '.join(missing)}")
    return {k: token.metadata[k] for k in keys}


def _day_iso(day: date | str) -> str:
    """Normalize ``date`` or already-ISO string to ``YYYY-MM-DD``."""
    if isinstance(day, date):
        return day.isoformat()
    return str(day)


def _to_ms(value: datetime | int) -> int:
    """Normalize ``datetime`` (UTC-aware) or already-int ms to int ms."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp() * 1000)
    return int(value)


async def _get_json(
    http_client: HttpClient,
    *,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    """Issue a GET, raise on non-200 / non-JSON, return parsed body."""
    response = await http_client.get(url, params=params, headers=headers)
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise AmazfitFetchError(f"GET {url} returned HTTP {response.status_code}: {body[:200]}")
    try:
        return response.json()
    except Exception as e:
        raise AmazfitFetchError(f"GET {url} returned non-JSON body") from e


async def fetch_user_info(http_client: HttpClient, *, token: OAuthToken) -> dict[str, Any]:
    """Fetch the operator's profile.

    Used as a token-alive smoke test by ``AmazfitSource.setup``. Returns
    the raw ``{code, data:{age,gender,height,weight,birthday,...}, message}``
    payload so callers can validate ``code == 1`` for success.
    """
    meta = _require_metadata(token, "base_url", "user_id")
    return await _get_json(
        http_client,
        url=f"{meta['base_url']}{PATH_USER_INFO}",
        params={"userid": meta["user_id"], "r": _r()},
        headers=_headers(token),
    )


async def fetch_heart_rate(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    from_time: datetime | int,
    to_time: datetime | int,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Fetch per-minute heart-rate readings in a millisecond range.

    Returns the raw ``{items: [...]}`` envelope. Per the live captured
    shape, items are stable enough to leave parsing to the normalizer.
    """
    meta = _require_metadata(token, "base_url", "user_id")
    path = PATH_HEART_RATE.format(user_id=meta["user_id"])
    return await _get_json(
        http_client,
        url=f"{meta['base_url']}{path}",
        params={
            "startTime": _to_ms(from_time),
            "endTime": _to_ms(to_time),
            "limit": limit,
            "type": 2,
            "r": _r(),
        },
        headers=_headers(token),
    )


async def fetch_band_data(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    day: date | str,
    query_type: str = "summary",
) -> dict[str, Any]:
    """Fetch the daily band-data summary for a single day.

    ``query_type=summary`` returns the JSON daily aggregate (steps,
    sleep summary, etc.). ``query_type=detail`` returns the same plus
    base64-encoded minute blobs — out of scope for v1 (operator can
    flip the kwarg in code if they want to inspect).
    """
    meta = _require_metadata(token, "base_url", "user_id")
    iso = _day_iso(day)
    return await _get_json(
        http_client,
        url=f"{meta['base_url']}{PATH_BAND_DATA}",
        params={
            "userid": meta["user_id"],
            "from_date": iso,
            "to_date": iso,
            "query_type": query_type,
            "byteLength": 8,
            "device_type": 0,
            "r": _r(),
        },
        headers=_headers(token),
    )


async def _fetch_events(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    event_type: str,
    from_time: datetime | int,
    to_time: datetime | int,
    sub_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Shared driver for /users/<id>/events queries (spo2, stress, ...)."""
    meta = _require_metadata(token, "base_url", "user_id")
    path = PATH_EVENTS.format(user_id=meta["user_id"])
    params: dict[str, Any] = {
        "eventType": event_type,
        "from": _to_ms(from_time),
        "to": _to_ms(to_time),
        "limit": limit,
        "reverse": "false",
        "userId": meta["user_id"],
        "r": _r(),
    }
    if sub_type is not None:
        params["subType"] = sub_type
    return await _get_json(
        http_client,
        url=f"{meta['base_url']}{path}",
        params=params,
        headers=_headers(token),
    )


async def fetch_spo2_events(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    from_time: datetime | int,
    to_time: datetime | int,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """SpO2 readings via the events endpoint (newer Amazfit models only)."""
    return await _fetch_events(
        http_client,
        token=token,
        event_type="blood_oxygen",
        sub_type="click",
        from_time=from_time,
        to_time=to_time,
        limit=limit,
    )


async def fetch_stress_events(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    from_time: datetime | int,
    to_time: datetime | int,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """All-day stress readings via the events endpoint."""
    return await _fetch_events(
        http_client,
        token=token,
        event_type="all_day_stress",
        from_time=from_time,
        to_time=to_time,
        limit=limit,
    )


async def fetch_sport_load(
    http_client: HttpClient,
    *,
    token: OAuthToken,
    start_day: date | str,
    end_day: date | str,
    limit: int = SPORT_LOAD_LIMIT,
) -> dict[str, Any]:
    """Daily training-load summary (wtlSum, optimal range, overreaching)."""
    meta = _require_metadata(token, "base_url", "user_id")
    path = PATH_SPORT_LOAD.format(user_id=meta["user_id"])
    return await _get_json(
        http_client,
        url=f"{meta['base_url']}{path}",
        params={
            "startDay": _day_iso(start_day),
            "endDay": _day_iso(end_day),
            "limit": limit,
            "isReverse": "true",
            "r": _r(),
        },
        headers=_headers(token),
    )
