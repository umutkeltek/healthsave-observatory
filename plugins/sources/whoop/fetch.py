"""Whoop developer API fetch for cycle / recovery / sleep / workout / body.

Each fetcher accepts an injected HTTP client (httpx.AsyncClient-shaped via
:class:`HttpClient` Protocol) and returns the raw Whoop payload records.
Normalization into ``IngestStorage`` sample dicts lives in
:mod:`plugins.sources.whoop.normalize` so the two boundaries can evolve
independently — the wire shape Whoop uses today may change without
touching the storage-side row shapes, and vice versa.

Pagination model (matches Whoop v2):

  * Response: ``{"records": [...], "next_token": "<opaque>"}``.
  * ``next_token`` is absent / null on the last page.
  * Cursor is passed back as ``?nextToken=...`` on the next call.
  * Date range filtering is ``?start=<iso>&end=<iso>``; ISO with a
    trailing ``Z`` is what the Whoop docs show.

The paginated fetcher functions are thin wrappers over
:func:`paginated_get` so each Whoop resource has a single clear call
site for tests + log correlation. Body measurement is a single-object
resource, so it uses :func:`fetch_one`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from . import API_BASE

# Whoop v2 path constants — names match the API documentation so a
# search for "/developer/v2/cycle" lands here. Whoop retired the v1 data
# endpoints (they now 404), and the v2 record/score shapes are what
# ``normalize.py`` already parses, so all five resources use v2.
PATH_CYCLE = "/developer/v2/cycle"
PATH_BODY = "/developer/v2/user/measurement/body"
PATH_RECOVERY = "/developer/v2/recovery"
PATH_SLEEP = "/developer/v2/activity/sleep"
PATH_WORKOUT = "/developer/v2/activity/workout"

# Page size we ask Whoop for. The API caps at 25 today; we ask explicitly
# so a future cap change does not silently shrink our fetch.
DEFAULT_PAGE_SIZE = 25


class WhoopFetchError(Exception):
    """Raised when a Whoop data endpoint returns non-200 or malformed JSON."""


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
        params: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def _format_since(since: datetime | None) -> str | None:
    """Whoop accepts ISO-8601 with a Z suffix. Strip any '+00:00' offset."""
    if since is None:
        return None
    return since.isoformat().replace("+00:00", "Z")


async def paginated_get(
    http_client: HttpClient,
    *,
    access_token: str,
    path: str,
    since: datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    """Walk ``next_token`` pagination and return all records.

    ``max_pages`` is a runaway-guard: 100 pages × 25 records = 2500
    records per fetch, which is well above the daily output of a single
    user. A real overflow indicates a date-range misconfiguration; we
    raise instead of looping silently.
    """
    records: list[dict[str, Any]] = []
    params: dict[str, str] = {"limit": str(page_size)}
    start = _format_since(since)
    if start is not None:
        params["start"] = start

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    for _ in range(max_pages):
        response = await http_client.get(f"{API_BASE}{path}", params=params, headers=headers)
        if response.status_code != 200:
            body = getattr(response, "text", "<no body>")
            raise WhoopFetchError(f"GET {path} returned HTTP {response.status_code}: {body}")
        try:
            payload = response.json()
        except Exception as e:
            raise WhoopFetchError(f"GET {path} returned non-JSON body") from e

        records.extend(payload.get("records", []))
        next_token = payload.get("next_token")
        if not next_token:
            return records
        params["nextToken"] = next_token

    raise WhoopFetchError(f"GET {path} exceeded max_pages={max_pages} — refusing to loop further")


async def fetch_one(
    http_client: HttpClient,
    *,
    access_token: str,
    path: str,
) -> dict[str, Any]:
    """GET a single Whoop resource by its fully-qualified path."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    response = await http_client.get(f"{API_BASE}{path}", headers=headers)
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise WhoopFetchError(f"GET {path} returned HTTP {response.status_code}: {body}")
    try:
        return response.json()
    except Exception as e:
        raise WhoopFetchError(f"GET {path} returned non-JSON body") from e


async def fetch_recovery(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Recovery records — one per cycle. Carries HRV, RHR, SpO2, skin temp."""
    return await paginated_get(
        http_client, access_token=access_token, path=PATH_RECOVERY, since=since
    )


async def fetch_body_measurement(
    http_client: HttpClient,
    *,
    access_token: str,
) -> dict[str, Any]:
    """User body measurement — single object: height_meter, weight_kilogram, max_heart_rate."""
    return await fetch_one(http_client, access_token=access_token, path=PATH_BODY)


async def fetch_sleep(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Sleep sessions — start/end + per-stage durations + respiratory rate."""
    return await paginated_get(http_client, access_token=access_token, path=PATH_SLEEP, since=since)


async def fetch_workouts(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Workouts — start/end, average + max HR, calories, distance, strain."""
    return await paginated_get(
        http_client, access_token=access_token, path=PATH_WORKOUT, since=since
    )


async def fetch_cycles(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Cycles — daily strain + average HR + calories summary."""
    return await paginated_get(http_client, access_token=access_token, path=PATH_CYCLE, since=since)
