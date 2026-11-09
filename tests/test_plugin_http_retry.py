"""A vendor GET is retried on a transient failure, a bounded number of times.

A 30-day backfill window is dozens of requests. With no per-request retry, a
vendor failing one request in twenty failed almost every widened poll, so the
backfill was eventually given up as a gap although nothing was wrong with the
range.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest


class _Response:
    def __init__(self, status_code: int, payload: Any = None, headers=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self) -> Any:
        return self._payload


class _Http:
    """Answers from a script, one entry per GET (an exception is raised)."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0

    async def get(self, url, *, params=None, headers=None):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def sleeps(monkeypatch):
    import plugin_sdk.http as http

    waited: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(http, "_sleep", fake_sleep)
    return waited


@pytest.mark.asyncio
async def test_a_whoop_page_that_fails_once_with_503_is_fetched(sleeps):
    from plugins.sources.whoop.fetch import PATH_RECOVERY, paginated_get

    http = _Http([_Response(503), _Response(200, {"records": [{"id": 1}]})])

    records = await paginated_get(http, access_token="AT", path=PATH_RECOVERY, since=None)

    assert records == [{"id": 1}]
    assert http.calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first",
    [
        _Response(500),
        _Response(502),
        _Response(504),
        _Response(408),
        _Response(429, headers={"Retry-After": "3"}),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
)
async def test_transient_failures_are_retried(sleeps, first):
    from plugin_sdk.http import get_with_retry

    http = _Http([first, _Response(200)])
    response = await get_with_retry(http, "https://vendor/x")
    assert response.status_code == 200
    assert http.calls == 2
    assert sleeps == ([3.0] if isinstance(first, _Response) and first.status_code == 429 else [1.0])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 422])
async def test_a_definite_answer_is_returned_at_once(sleeps, status):
    from plugin_sdk.http import get_with_retry

    http = _Http([_Response(status)])
    response = await get_with_retry(http, "https://vendor/x")
    assert response.status_code == status
    assert http.calls == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_retries_are_bounded_and_the_last_answer_is_returned(sleeps):
    from plugin_sdk.http import get_with_retry

    http = _Http([_Response(503), _Response(503), _Response(503), _Response(200)])
    response = await get_with_retry(http, "https://vendor/x")
    assert response.status_code == 503, "a real outage still fails the request"
    assert http.calls == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_a_persistent_timeout_raises_after_the_last_attempt(sleeps):
    from plugin_sdk.http import get_with_retry

    http = _Http([httpx.ReadTimeout("slow")] * 3)
    with pytest.raises(httpx.ReadTimeout):
        await get_with_retry(http, "https://vendor/x")
    assert http.calls == 3


@pytest.mark.asyncio
async def test_a_long_retry_after_is_capped(sleeps):
    from plugin_sdk.http import MAX_DELAY_S, get_with_retry

    http = _Http([_Response(429, headers={"Retry-After": "3600"}), _Response(200)])
    await get_with_retry(http, "https://vendor/x")
    assert sleeps == [MAX_DELAY_S]


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin", ["amazfit", "polar", "google_health", "whoop_one"])
async def test_every_source_fetch_retries_a_transient_failure(sleeps, plugin):
    """Each plugin's GET goes through the retry, not only Whoop's pages."""
    from datetime import UTC, datetime

    from auth import DEFAULT_OWNER_ID, OAuthToken

    ok = {
        "amazfit": {"items": []},
        "polar": [],
        "google_health": {"dataPoints": []},
        "whoop_one": {"id": 1},
    }[plugin]
    http = _Http([_Response(503), _Response(200, ok)])
    if plugin == "amazfit":
        from plugins.sources.amazfit.fetch import fetch_heart_rate

        token = OAuthToken(
            owner_id=DEFAULT_OWNER_ID,
            provider="amazfit",
            access_token="AT",
            refresh_token=None,
            expires_at=None,
            metadata={"base_url": "https://api.example", "user_id": "1"},
        )
        await fetch_heart_rate(
            http,
            token=token,
            from_time=datetime(2026, 11, 1, tzinfo=UTC),
            to_time=datetime(2026, 11, 2, tzinfo=UTC),
        )
    elif plugin == "polar":
        from plugins.sources.polar.fetch import fetch_exercises

        await fetch_exercises(http, access_token="AT")
    elif plugin == "google_health":
        from plugins.sources.google_health.fetch import fetch_steps

        await fetch_steps(http, access_token="AT", since=datetime(2026, 11, 1, tzinfo=UTC))
    else:
        from plugins.sources.whoop.fetch import PATH_SLEEP, fetch_one

        await fetch_one(http, access_token="AT", path=f"{PATH_SLEEP}/1")
    assert http.calls == 2
