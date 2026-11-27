"""E2E: a dead token never uses up the backfill attempts.

The worker widens a poll's window back to the last successful poll, and gives
the wide window up after a few failed polls (a vendor page cap, a rejected
range). Those failures must be range failures. A Whoop token that died made
every poll fail on the refresh, so three polls (about 1.5 h) used up the
attempts: when the person re-authorized days later, the first poll fell back
to the default window and the outage became a permanent gap, the very case
the cursor exists for.

Runs the real worker poll and the real Whoop plugin on real PostgreSQL, with a
fake Whoop HTTP API.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _Whoop:
    """Token endpoint and data API; records the window each data call asks for."""

    def __init__(self) -> None:
        self.refresh_status = 400
        self.data_status = 200
        # Status for a window starting more than two days back (a widened
        # poll); None answers it like any other window.
        self.wide_status: int | None = None
        self.starts: list[str | None] = []

    async def __aenter__(self) -> _Whoop:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url, *, data=None, headers=None):
        if self.refresh_status != 200:
            return _Response(self.refresh_status, {"error": "invalid_grant"})
        return _Response(
            200,
            {
                "access_token": "AT-new",
                "refresh_token": "RT-new",
                "expires_in": 3600,
                "scope": "offline",
                "token_type": "Bearer",
            },
        )

    async def get(self, url, *, params=None, headers=None):
        start = (params or {}).get("start")
        self.starts.append(start)
        if self.wide_status is not None and start is not None:
            begins = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if begins < datetime.now(UTC) - timedelta(days=2):
                return _Response(self.wide_status, {"error": "gateway timeout"})
        if self.data_status != 200:
            return _Response(self.data_status, {"error": "rejected"})
        return _Response(200, {"records": []})


def _token(*, expired: bool, refresh_token: str):
    from auth import DEFAULT_OWNER_ID, OAuthToken

    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider="whoop",
        access_token="AT",
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + (timedelta(minutes=-5) if expired else timedelta(hours=1)),
        scopes=("offline",),
    )


@pytest.fixture
async def whoop_poll(monkeypatch):
    """The real worker Whoop poll against the e2e DB, with a fake Whoop API."""
    import httpx
    import worker.sources as worker_sources
    from auth import DEFAULT_OWNER_ID, generate_key
    from auth.encryption import _fernet_from_env
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    for name in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("HDH_TOKEN_ENC_KEY", generate_key())
    _fernet_from_env.cache_clear()

    whoop = _Whoop()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: whoop)

    async def no_fusion(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(worker_sources, "reconcile_source_poll_sessions", no_fusion)

    engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def clean() -> None:
        async with factory() as session:
            for table in ("source_poll_cursors", "oauth_tokens", "oauth_token_events"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE owner_id = :owner AND provider = 'whoop'"),
                    {"owner": DEFAULT_OWNER_ID},
                )
            await session.commit()

    await clean()
    try:
        yield whoop, factory, worker_sources.make_whoop_poll(factory)
    finally:
        await clean()
        await engine.dispose()
        _fernet_from_env.cache_clear()


async def _failures(factory) -> int:
    """Rejected-range failures (the 3-poll limit)."""
    from storage.timescale.source_poll_cursors import get_poll_cursor

    async with factory() as session:
        return (await get_poll_cursor(session, provider="whoop")).backfill_failures


async def _outage_failures(factory) -> int:
    """Server-error and read-timeout failures (the 12-poll limit)."""
    from storage.timescale.source_poll_cursors import get_poll_cursor

    async with factory() as session:
        return (await get_poll_cursor(session, provider="whoop")).backfill_outage_failures


@pytest.mark.asyncio
async def test_a_dead_token_for_three_days_then_re_auth_gets_the_full_backfill(whoop_poll):
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    whoop, factory, poll = whoop_poll
    last_success = datetime.now(UTC) - timedelta(days=3)
    async with factory() as session:
        await record_successful_poll(session, provider="whoop", polled_at=last_success)
        await oauth_tokens.put_token(session, _token(expired=True, refresh_token="RT-dead"))
        await session.commit()

    # The token is dead: every widened poll fails on the refresh.
    for _ in range(4):
        with pytest.raises(Exception, match="token endpoint returned HTTP 400"):
            await poll()
    assert await _failures(factory) == 0, "a refresh failure is not a backfill failure"

    # The person re-authorizes.
    async with factory() as session:
        await oauth_tokens.put_token(session, _token(expired=False, refresh_token="RT-new"))
        await session.commit()

    await poll()

    expected = (last_success - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    windowed = [start for start in whoop.starts if start is not None]  # paginated fetches
    assert windowed and set(windowed) == {expected}


@pytest.mark.asyncio
async def test_a_vendor_outage_of_any_length_keeps_its_backfill(whoop_poll):
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    whoop, factory, poll = whoop_poll
    async with factory() as session:
        await record_successful_poll(
            session, provider="whoop", polled_at=datetime.now(UTC) - timedelta(days=3)
        )
        await oauth_tokens.put_token(session, _token(expired=False, refresh_token="RT"))
        await session.commit()

    # The whole vendor is down, well past the outage threshold: neither the
    # widened nor the default window answers, so nothing is held against the
    # backfill.
    # (A 401 makes the plugin try one refresh, which this token endpoint
    # refuses with a 400: either way the poll fails without counting.)
    for status in (503, 502, 401, 429, 504) * 3:
        whoop.data_status = status
        with pytest.raises(Exception, match=f"HTTP {400 if status == 401 else status}"):
            await poll()

    assert await _failures(factory) == 0
    assert await _outage_failures(factory) == 0

    whoop.data_status = 200
    whoop.starts.clear()
    await poll()
    windowed = [start for start in whoop.starts if start is not None]
    oldest = min(datetime.fromisoformat(start.replace("Z", "+00:00")) for start in windowed)
    assert oldest < datetime.now(UTC) - timedelta(days=3), "the backfill still runs"


@pytest.mark.asyncio
async def test_a_rejected_range_still_counts(whoop_poll):
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    whoop, factory, poll = whoop_poll
    async with factory() as session:
        await record_successful_poll(
            session, provider="whoop", polled_at=datetime.now(UTC) - timedelta(days=3)
        )
        await oauth_tokens.put_token(session, _token(expired=False, refresh_token="RT"))
        await session.commit()

    whoop.data_status = 400
    with pytest.raises(Exception, match="HTTP 400"):
        await poll()

    assert await _failures(factory) == 1


@pytest.mark.asyncio
async def test_re_authorizing_resets_the_backfill_attempts(whoop_poll):
    """Re-authorizing gives the widened window its attempts back."""
    from sqlalchemy import text
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    whoop, factory, poll = whoop_poll
    last_success = datetime.now(UTC) - timedelta(days=3)
    async with factory() as session:
        await record_successful_poll(session, provider="whoop", polled_at=last_success)
        # As if 3 widened polls had failed.
        await session.execute(
            text(
                "UPDATE source_poll_cursors SET backfill_failures = 3, "
                "backfill_outage_failures = 12 WHERE provider = 'whoop'"
            )
        )
        await session.commit()

    async with factory() as session:
        await oauth_tokens.put_token(session, _token(expired=False, refresh_token="RT-new"))
        await session.commit()
    assert await _failures(factory) == 0
    assert await _outage_failures(factory) == 0

    await poll()

    expected = (last_success - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    windowed = [start for start in whoop.starts if start is not None]
    assert windowed and set(windowed) == {expected}


@pytest.mark.asyncio
async def test_a_routine_refresh_does_not_reset_the_backfill_attempts(whoop_poll):
    """Whoop access tokens last an hour: a refresh must not wipe the count."""
    from sqlalchemy import text
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    _whoop, factory, _poll = whoop_poll
    async with factory() as session:
        await record_successful_poll(
            session, provider="whoop", polled_at=datetime.now(UTC) - timedelta(days=3)
        )
        await session.execute(
            text("UPDATE source_poll_cursors SET backfill_failures = 2 WHERE provider = 'whoop'")
        )
        await oauth_tokens.put_token(
            session, _token(expired=False, refresh_token="RT"), event_kind="refreshed"
        )
        await session.commit()

    assert await _failures(factory) == 2


# worker.sources.MAX_BACKFILL_OUTAGE_FAILURES (pinned in test_source_poll_backfill).
OUTAGE_THRESHOLD = 12


@pytest.mark.asyncio
async def test_a_widened_window_that_always_times_out_is_given_up_after_the_threshold(
    whoop_poll,
):
    """504 for the wide range every time, while the default range works.

    A range that never succeeds is abandoned after OUTAGE_THRESHOLD polls with
    the gap recorded, instead of being retried forever while the default
    window would have worked.
    """
    from sqlalchemy import text
    from storage.timescale import oauth_tokens
    from storage.timescale.source_poll_cursors import record_successful_poll

    whoop, factory, poll = whoop_poll
    last_success = datetime.now(UTC) - timedelta(days=3)
    async with factory() as session:
        await record_successful_poll(session, provider="whoop", polled_at=last_success)
        await oauth_tokens.put_token(session, _token(expired=False, refresh_token="RT"))
        await session.commit()
    whoop.wide_status = 504

    for _ in range(OUTAGE_THRESHOLD - 1):
        with pytest.raises(Exception, match="HTTP 504"):
            await poll()
    # Still inside the threshold: the poll keeps asking for the backfill.
    with pytest.raises(Exception, match="HTTP 504"):
        await poll()

    # Each failed run also asked for the default window (and kept its data);
    # the cursor stayed, so the gap was still open.
    assert await _outage_failures(factory) == OUTAGE_THRESHOLD
    async with factory() as session:
        kept = (
            await session.execute(
                text("SELECT last_success_at FROM source_poll_cursors WHERE provider = 'whoop'")
            )
        ).scalar_one()
    assert kept == last_success

    whoop.starts.clear()
    await poll()  # falls back to the default window, which succeeds

    windowed = [start for start in whoop.starts if start is not None]
    assert windowed
    oldest = min(datetime.fromisoformat(start.replace("Z", "+00:00")) for start in windowed)
    assert oldest > datetime.now(UTC) - timedelta(days=2)
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT last_success_at, unfilled_gap_start FROM source_poll_cursors "
                    "WHERE provider = 'whoop'"
                )
            )
        ).one()
    assert row.last_success_at > last_success
    assert row.unfilled_gap_start == last_success - timedelta(days=1)
