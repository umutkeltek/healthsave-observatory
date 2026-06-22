"""Polar AccessLink v3 fetch helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .oauth import POLAR_API_BASE

PATH_EXERCISES = "/v3/exercises"


class PolarFetchError(Exception):
    """Raised when Polar API response cannot be used."""


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any] | list[dict[str, Any]]: ...


class HttpClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


async def fetch_exercises(
    http_client: HttpClient,
    *,
    access_token: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent Polar exercises.

    Polar's non-transactional endpoint returns recent exercises available after
    registration. ``since`` is accepted so scheduler callers share the source
    plugin shape; Polar currently does not expose this filter here.
    """

    _ = since
    response = await http_client.get(
        f"{POLAR_API_BASE}{PATH_EXERCISES}",
        params={"samples": "false", "zones": "false"},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise PolarFetchError(f"GET {PATH_EXERCISES} returned HTTP {response.status_code}: {body}")
    try:
        payload = response.json()
    except Exception as exc:
        raise PolarFetchError(f"GET {PATH_EXERCISES} returned non-JSON body") from exc
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        raw = payload.get("exercises", [])
        return [item for item in raw if isinstance(item, dict)]
    payload_type = type(payload).__name__
    raise PolarFetchError(f"GET {PATH_EXERCISES} returned unsupported payload {payload_type}")
