"""Google Health API v4 data point fetch helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

GOOGLE_HEALTH_API_BASE = "https://health.googleapis.com"
DATA_TYPE_STEPS = "steps"
DEFAULT_PAGE_SIZE = 1000


class GoogleHealthFetchError(Exception):
    """Raised when Google Health API response cannot be used."""


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class HttpClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def _format_since(since: datetime | None) -> str | None:
    if since is None:
        return None
    return since.isoformat().replace("+00:00", "Z")


def _data_points_url(data_type: str) -> str:
    return f"{GOOGLE_HEALTH_API_BASE}/v4/users/me/dataTypes/{data_type}/dataPoints"


async def fetch_data_points(
    http_client: HttpClient,
    *,
    access_token: str,
    data_type: str,
    since: datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    """Fetch data points for one Google Health data type."""

    params: dict[str, str] = {"pageSize": str(page_size)}
    start = _format_since(since)
    if start is not None:
        params["filter"] = f'{data_type}.interval.start_time >= "{start}"'

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    points: list[dict[str, Any]] = []

    for _ in range(max_pages):
        response = await http_client.get(
            _data_points_url(data_type), params=params, headers=headers
        )
        if response.status_code != 200:
            body = getattr(response, "text", "<no body>")
            raise GoogleHealthFetchError(
                f"GET dataPoints/{data_type} returned HTTP {response.status_code}: {body}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise GoogleHealthFetchError(
                f"GET dataPoints/{data_type} returned non-JSON body"
            ) from exc

        raw_points = payload.get("dataPoints", [])
        points.extend(item for item in raw_points if isinstance(item, dict))

        next_token = payload.get("nextPageToken")
        if not next_token:
            return points
        params["pageToken"] = str(next_token)

    raise GoogleHealthFetchError(
        f"GET dataPoints/{data_type} exceeded max_pages={max_pages} refusing loop further"
    )


async def fetch_steps(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    return await fetch_data_points(
        http_client,
        access_token=access_token,
        data_type=DATA_TYPE_STEPS,
        since=since,
    )
