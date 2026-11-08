"""Token state a source poll writes survives the poll failing afterwards.

Whoop and Google rotate the refresh token on every successful refresh: the
old one stops working at once. The worker used to commit the poll session
only after ingest, so a refresh followed by any later failure (a fetch 5xx, a
bad sample) rolled the new token back and left the old, dead one stored. The
connector then failed for good until someone re-authorized it. A refresh
failure was rolled back the same way, so a dead connector left no trace.

These tests run the real worker seam (``make_source_poll``) with a session
that keeps pending writes until commit and drops them on rollback, like a
database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from auth import DEFAULT_OWNER_ID, OAuthToken
from worker.sources import (
    make_amazfit_poll,
    make_google_health_poll,
    make_polar_poll,
    make_whoop_poll,
)


class _TxSession:
    """Writes stay pending until commit; rollback discards them."""

    def __init__(self) -> None:
        self.pending: list[tuple] = []
        self.committed: list[tuple] = []

    async def __aenter__(self) -> _TxSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self.pending = []  # closing a session rolls back anything uncommitted
        return False

    async def commit(self) -> None:
        self.committed.extend(self.pending)
        self.pending = []

    async def rollback(self) -> None:
        self.pending = []


@dataclass
class _Response:
    status_code: int
    payload: Any
    text: str = ""

    def json(self) -> Any:
        return self.payload


class _Http:
    def __init__(self, *, posts: dict[str, _Response], gets: dict[str, _Response]) -> None:
        self._posts = posts
        self._gets = gets

    async def __aenter__(self) -> _Http:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url, **_kwargs):
        return next(r for needle, r in self._posts.items() if needle in url)

    async def get(self, url, **_kwargs):
        return next(r for needle, r in self._gets.items() if needle in url)


def _token(provider: str, *, expired: bool) -> OAuthToken:
    delta = timedelta(minutes=-5) if expired else timedelta(hours=1)
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=provider,
        access_token="AT-old",
        refresh_token="RT-old",
        expires_at=datetime.now(UTC) + delta,
        scopes=("offline",),
    )


@pytest.fixture
def token_store(monkeypatch):
    """Route the default token store's writes into the poll session."""
    from storage.timescale import oauth_tokens

    stored: dict[str, OAuthToken] = {}

    async def get_token(session, *, provider, owner_id=DEFAULT_OWNER_ID):
        return stored.get(provider)

    async def put_token(session, token, *, event_kind="authorized"):
        session.pending.append(("put_token", token.provider, token.refresh_token, event_kind))

    async def record_refresh_failure(session, *, provider, error_message, owner_id=None):
        session.pending.append(("refresh_failed", provider))

    monkeypatch.setattr(oauth_tokens, "get_token", get_token)
    monkeypatch.setattr(oauth_tokens, "put_token", put_token)
    monkeypatch.setattr(oauth_tokens, "record_refresh_failure", record_refresh_failure)
    return stored


def _run_poll(monkeypatch, make_poll, http: _Http) -> tuple[_TxSession, Any]:
    import httpx

    session = _TxSession()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: http)
    return session, make_poll(lambda: session)


_REFRESHED = {
    "access_token": "AT-new",
    "refresh_token": "RT-new",
    "expires_in": 3600,
    "scope": "offline",
    "token_type": "Bearer",
}


@pytest.mark.asyncio
async def test_whoop_refresh_survives_a_fetch_failure_after_it(monkeypatch, token_store):
    for name in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI"):
        monkeypatch.setenv(name, "x")
    token_store["whoop"] = _token("whoop", expired=True)
    http = _Http(
        posts={"oauth2/token": _Response(200, _REFRESHED)},
        gets={"": _Response(503, {}, text="whoop is down")},
    )
    session, poll = _run_poll(monkeypatch, make_whoop_poll, http)

    with pytest.raises(Exception, match="HTTP 503"):
        await poll()

    assert ("put_token", "whoop", "RT-new", "refreshed") in session.committed


@pytest.mark.asyncio
async def test_whoop_refresh_failure_is_persisted(monkeypatch, token_store):
    for name in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI"):
        monkeypatch.setenv(name, "x")
    token_store["whoop"] = _token("whoop", expired=True)
    http = _Http(
        posts={"oauth2/token": _Response(400, {"error": "invalid_grant"}, text="invalid_grant")},
        gets={},
    )
    session, poll = _run_poll(monkeypatch, make_whoop_poll, http)

    with pytest.raises(Exception, match="HTTP 400"):
        await poll()

    assert ("refresh_failed", "whoop") in session.committed


@pytest.mark.asyncio
async def test_google_health_refresh_survives_a_fetch_failure_after_it(monkeypatch, token_store):
    for name in (
        "GOOGLE_HEALTH_CLIENT_ID",
        "GOOGLE_HEALTH_CLIENT_SECRET",
        "GOOGLE_HEALTH_REDIRECT_URI",
    ):
        monkeypatch.setenv(name, "x")
    token_store["google-health-api"] = _token("google-health-api", expired=True)
    http = _Http(
        posts={"oauth2.googleapis.com/token": _Response(200, _REFRESHED)},
        gets={"": _Response(503, {}, text="google is down")},
    )
    session, poll = _run_poll(monkeypatch, make_google_health_poll, http)

    with pytest.raises(Exception, match="HTTP 503"):
        await poll()

    assert ("put_token", "google-health-api", "RT-new", "refreshed") in session.committed


@pytest.mark.asyncio
async def test_amazfit_expired_token_failure_is_persisted(monkeypatch, token_store):
    token_store["amazfit"] = _token("amazfit", expired=True)
    session, poll = _run_poll(monkeypatch, make_amazfit_poll, _Http(posts={}, gets={}))

    with pytest.raises(Exception, match="expired"):
        await poll()

    assert ("refresh_failed", "amazfit") in session.committed


@pytest.mark.asyncio
async def test_polar_expired_token_failure_is_persisted(monkeypatch, token_store):
    token_store["polar-accesslink"] = _token("polar-accesslink", expired=True)
    session, poll = _run_poll(monkeypatch, make_polar_poll, _Http(posts={}, gets={}))

    with pytest.raises(Exception, match="expired"):
        await poll()

    assert ("refresh_failed", "polar-accesslink") in session.committed
