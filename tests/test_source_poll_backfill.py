"""A source poll backfills from its last successful poll after an outage.

Each poll fetched a fixed window ("now minus 1 day" for Whoop and Amazfit,
"now minus 7 days" for Polar and Google), with no record of when a poll last
succeeded. Any outage longer than that window (a dead token, the vendor down,
the worker stopped) left a permanent gap. The worker now keeps a per-provider,
per-owner "last successful poll" cursor and widens the window to cover the gap,
bounded so one poll never asks a vendor for unbounded history.

A widened window that keeps failing (a page cap, a vendor rejecting the range)
must not be retried forever: after MAX_BACKFILL_FAILURES failed widened polls
the worker polls the default window again and records the gap it gave up on.
A poll skipped for want of a token is not a successful poll.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import worker.sources as worker_sources
from storage.timescale import source_poll_cursors
from storage.timescale.source_poll_cursors import PollCursor
from worker.sources import (
    MAX_BACKFILL,
    MAX_BACKFILL_FAILURES,
    MAX_BACKFILL_OUTAGE_FAILURES,
    make_whoop_poll,
)

from plugins.sources.whoop import DEFAULT_LOOKBACK, WhoopSource
from plugins.sources.whoop.fetch import WhoopFetchError
from plugins.sources.whoop.oauth import WhoopOAuthError


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Http:
    async def __aenter__(self) -> _Http:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def poll(monkeypatch):
    """Run the real Whoop poll seam with a recorded ingest and an in-memory cursor."""

    state: dict[str, Any] = {
        "cursor": None,
        "failures": 0,
        "outage_failures": 0,
        "recorded": [],
        "gaps": [],
        "payloads": [],
        "result": {"accepted": 0, "rejected": 0},
        "fail": False,
    }

    async def get_poll_cursor(session, *, provider, owner_id):
        assert provider == "whoop"
        if state["cursor"] is None:
            return None
        return PollCursor(
            last_success_at=state["cursor"],
            backfill_failures=state["failures"],
            backfill_outage_failures=state["outage_failures"],
        )

    async def record_successful_poll(session, *, provider, owner_id, polled_at, unfilled_gap=None):
        state["recorded"].append(polled_at)
        state["gaps"].append(unfilled_gap)
        state["cursor"] = polled_at
        state["failures"] = 0
        state["outage_failures"] = 0

    async def record_backfill_failure(session, *, provider, owner_id, outage=False):
        state["outage_failures" if outage else "failures"] += 1

    monkeypatch.setattr(source_poll_cursors, "get_poll_cursor", get_poll_cursor)
    monkeypatch.setattr(source_poll_cursors, "record_successful_poll", record_successful_poll)
    monkeypatch.setattr(source_poll_cursors, "record_backfill_failure", record_backfill_failure)

    async def ingest(self, payload):
        state["payloads"].append(payload)
        if state["fail"] is True:
            raise RuntimeError("whoop is down")
        if state["fail"] == "wide" and "since" in payload:
            raise WhoopFetchError("GET /v2/recovery returned HTTP 400: range", status_code=400)
        if state["fail"] == "wide504" and "since" in payload:
            raise WhoopFetchError("GET /v2/recovery returned HTTP 504: timeout", status_code=504)
        if state["fail"] == "wide_read_timeout" and "since" in payload:
            raise httpx.ReadTimeout("read timed out")
        if state["fail"] == "wide429" and "since" in payload:
            raise WhoopFetchError("GET /v2/recovery returned HTTP 429: slow down", status_code=429)
        if state["fail"] == "down503":
            raise WhoopFetchError("GET /v2/recovery returned HTTP 503: down", status_code=503)
        if state["fail"] == "down_read_timeout":
            raise httpx.ReadTimeout("read timed out")
        return dict(state["result"])

    async def no_fusion(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(WhoopSource, "ingest", ingest)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _Http())
    monkeypatch.setattr(worker_sources, "reconcile_source_poll_sessions", no_fusion)

    async def run() -> _Session:
        session = _Session()
        job = make_whoop_poll(lambda: session)
        with contextlib.suppress(RuntimeError, WhoopFetchError, httpx.ReadTimeout):
            await job()
        return session

    state["run"] = run
    return state


@pytest.mark.asyncio
async def test_an_outage_longer_than_the_lookback_is_backfilled(poll):
    last_success = datetime.now(UTC) - timedelta(days=10)
    poll["cursor"] = last_success

    await poll["run"]()

    assert poll["payloads"][0]["since"] == last_success - DEFAULT_LOOKBACK


@pytest.mark.asyncio
async def test_the_backfill_window_is_bounded(poll):
    poll["cursor"] = datetime.now(UTC) - timedelta(days=400)

    started = datetime.now(UTC)
    await poll["run"]()
    finished = datetime.now(UTC)

    since = poll["payloads"][0]["since"]
    assert started - MAX_BACKFILL <= since <= finished - MAX_BACKFILL


@pytest.mark.asyncio
async def test_a_healthy_poll_keeps_the_plugin_default_window(poll):
    poll["cursor"] = datetime.now(UTC) - timedelta(minutes=30)

    await poll["run"]()

    assert "since" not in poll["payloads"][0]


@pytest.mark.asyncio
async def test_first_poll_keeps_the_plugin_default_window_and_records_the_cursor(poll):
    started = datetime.now(UTC)

    session = await poll["run"]()

    assert "since" not in poll["payloads"][0]
    [recorded] = poll["recorded"]
    assert started <= recorded <= datetime.now(UTC)
    assert session.commits >= 1


@pytest.mark.asyncio
async def test_a_failed_poll_does_not_move_the_cursor(poll):
    poll["cursor"] = datetime.now(UTC) - timedelta(days=3)
    poll["fail"] = True

    session = await poll["run"]()

    assert poll["recorded"] == []
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_a_widened_window_that_keeps_failing_falls_back_to_the_default(poll):
    last_success = datetime.now(UTC) - timedelta(days=10)
    poll["cursor"] = last_success
    poll["fail"] = "wide"  # the vendor rejects the wide range, not the default one

    for _ in range(MAX_BACKFILL_FAILURES):
        await poll["run"]()
    assert poll["failures"] == MAX_BACKFILL_FAILURES
    assert poll["recorded"] == []

    await poll["run"]()

    narrowed = poll["payloads"][-1]
    assert "since" not in narrowed, "the poll must fall back to the default window"
    [gap] = poll["gaps"]
    assert gap is not None
    gap_start, gap_end = gap
    assert gap_start == last_success - DEFAULT_LOOKBACK
    assert gap_end <= datetime.now(UTC) - DEFAULT_LOOKBACK
    assert poll["failures"] == 0


@pytest.mark.asyncio
async def test_a_failing_default_window_poll_does_not_count_as_a_backfill_failure(poll):
    """Outage polls with the default window must not use up the wide retries."""
    poll["cursor"] = datetime.now(UTC) - timedelta(minutes=30)
    poll["fail"] = True

    for _ in range(MAX_BACKFILL_FAILURES + 1):
        await poll["run"]()

    assert poll["failures"] == 0


@pytest.mark.asyncio
async def test_a_poll_skipped_for_want_of_a_token_does_not_move_the_cursor(poll):
    poll["cursor"] = datetime.now(UTC) - timedelta(days=10)
    poll["result"] = {"accepted": 0, "rejected": 0, "skipped_no_token": 1}

    await poll["run"]()

    assert poll["recorded"] == []


@pytest.mark.parametrize(
    ("exc", "counted"),
    [
        (WhoopFetchError("HTTP 400", status_code=400), True),
        (WhoopFetchError("HTTP 422", status_code=422), True),
        (WhoopFetchError("exceeded max_pages=100"), True),
        (WhoopFetchError("HTTP 401", status_code=401), False),
        (WhoopFetchError("HTTP 403", status_code=403), False),
        (WhoopFetchError("HTTP 429", status_code=429), False),
        (WhoopFetchError("HTTP 503", status_code=503), False),
        (WhoopOAuthError("token endpoint returned HTTP 400"), False),
        (RuntimeError("anything else"), False),
    ],
)
def test_only_range_failures_count_against_a_widened_window(exc, counted) -> None:
    from worker.sources import is_backfill_range_failure

    assert is_backfill_range_failure(exc, WhoopFetchError) is counted
    assert is_backfill_range_failure(httpx.ConnectError("down"), WhoopFetchError) is False
    assert is_backfill_range_failure(exc, None) is False


def test_every_source_poll_names_its_fetch_error() -> None:
    from worker.sources import (
        AMAZFIT_SPEC,
        GOOGLE_HEALTH_SPEC,
        POLAR_SPEC,
        WHOOP_SPEC,
        _load_entrypoint,
    )

    for spec in (WHOOP_SPEC, AMAZFIT_SPEC, POLAR_SPEC, GOOGLE_HEALTH_SPEC):
        error = _load_entrypoint(spec.fetch_error)
        assert error.__name__.endswith("FetchError")
        assert error("x", status_code=400).status_code == 400


def test_each_poll_keys_its_cursor_by_the_token_provider_it_authorizes() -> None:
    """put_token('authorized') resets the cursor stored under the token's provider."""
    from worker.sources import AMAZFIT_SPEC, GOOGLE_HEALTH_SPEC, POLAR_SPEC, WHOOP_SPEC

    from plugins.sources.amazfit import PROVIDER as AMAZFIT
    from plugins.sources.google_health import GOOGLE_HEALTH_PROVIDER
    from plugins.sources.polar import POLAR_PROVIDER
    from plugins.sources.whoop import PROVIDER as WHOOP

    assert WHOOP_SPEC.cursor_provider == WHOOP
    assert AMAZFIT_SPEC.cursor_provider == AMAZFIT
    assert POLAR_SPEC.cursor_provider == POLAR_PROVIDER
    assert GOOGLE_HEALTH_SPEC.cursor_provider == GOOGLE_HEALTH_PROVIDER


def test_the_outage_threshold_is_twelve_polls() -> None:
    """About 6 h on the 30-minute cron; the e2e test runs exactly this many."""
    assert MAX_BACKFILL_OUTAGE_FAILURES == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["wide504", "wide_read_timeout", "wide429"])
async def test_a_widened_window_that_keeps_timing_out_is_given_up_after_the_outage_threshold(
    poll, mode
):
    """The vendor answers the default window but never the wide one."""
    last_success = datetime.now(UTC) - timedelta(days=10)
    poll["cursor"] = last_success
    poll["fail"] = mode

    for _ in range(MAX_BACKFILL_OUTAGE_FAILURES - 1):
        await poll["run"]()
    assert "since" in poll["payloads"][-2], "a short outage keeps its backfill"
    await poll["run"]()
    assert poll["failures"] == 0
    assert poll["outage_failures"] == MAX_BACKFILL_OUTAGE_FAILURES
    assert poll["recorded"] == []

    await poll["run"]()

    assert "since" not in poll["payloads"][-1]
    [gap] = poll["gaps"]
    assert gap is not None and gap[0] == last_success - DEFAULT_LOOKBACK
    assert poll["outage_failures"] == 0


@pytest.mark.asyncio
async def test_a_failing_wide_window_still_brings_in_the_default_window(poll):
    """While the backfill is retried, recent data keeps arriving; the cursor stays."""
    last_success = datetime.now(UTC) - timedelta(days=10)
    poll["cursor"] = last_success
    poll["fail"] = "wide504"

    session = await poll["run"]()

    wide, probe = poll["payloads"]
    assert "since" in wide
    assert "since" not in probe, "the same run asks for the default window"
    assert session.commits == 1, "the default window's data and the count commit together"
    assert poll["outage_failures"] == 1
    assert poll["cursor"] == last_success, "the gap is still open"
    assert poll["recorded"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["down503", "down_read_timeout"])
async def test_a_vendor_that_is_down_never_uses_up_the_backfill(poll, mode):
    """Neither window answers: an outage of any length keeps its backfill."""
    last_success = datetime.now(UTC) - timedelta(days=10)
    poll["cursor"] = last_success
    poll["fail"] = mode

    for _ in range(MAX_BACKFILL_OUTAGE_FAILURES * 3):
        session = await poll["run"]()

    assert poll["outage_failures"] == 0
    assert poll["failures"] == 0
    assert session.commits == 0
    assert "since" in poll["payloads"][-2], "every run still asks for the backfill"

    poll["fail"] = False
    await poll["run"]()
    assert poll["payloads"][-1]["since"] == last_success - DEFAULT_LOOKBACK
    assert poll["gaps"] == [None]


@pytest.mark.asyncio
async def test_a_default_window_skipped_for_want_of_a_token_counts_nothing(poll):
    poll["cursor"] = datetime.now(UTC) - timedelta(days=10)
    poll["fail"] = "wide504"
    poll["result"] = {"accepted": 0, "rejected": 0, "skipped_no_token": 1}

    session = await poll["run"]()

    assert poll["outage_failures"] == 0
    assert session.commits == 0


@pytest.mark.parametrize(
    ("exc", "outage"),
    [
        (WhoopFetchError("HTTP 500", status_code=500), True),
        (WhoopFetchError("HTTP 503", status_code=503), True),
        (WhoopFetchError("HTTP 504", status_code=504), True),
        (WhoopFetchError("HTTP 408", status_code=408), True),
        (WhoopFetchError("HTTP 429", status_code=429), True),
        (WhoopFetchError("HTTP 400", status_code=400), False),
        (WhoopFetchError("HTTP 401", status_code=401), False),
        (WhoopFetchError("HTTP 403", status_code=403), False),
        (WhoopFetchError("exceeded max_pages=100"), False),
        (WhoopOAuthError("token endpoint returned HTTP 503"), False),
        (RuntimeError("anything else"), False),
    ],
)
def test_server_errors_timeouts_and_rate_limits_are_outage_failures(exc, outage) -> None:
    from worker.sources import is_backfill_outage_failure

    assert is_backfill_outage_failure(exc, WhoopFetchError) is outage
    assert is_backfill_outage_failure(exc, None) is False


def test_a_read_timeout_is_an_outage_failure_but_a_connect_failure_is_not() -> None:
    from worker.sources import is_backfill_outage_failure

    assert is_backfill_outage_failure(httpx.ReadTimeout("slow"), WhoopFetchError) is True
    assert is_backfill_outage_failure(httpx.ConnectTimeout("down"), WhoopFetchError) is False
    assert is_backfill_outage_failure(httpx.ConnectError("down"), WhoopFetchError) is False


def test_a_failure_is_never_both_a_range_and_an_outage_failure() -> None:
    from worker.sources import is_backfill_outage_failure, is_backfill_range_failure

    for status in range(400, 600):
        exc = WhoopFetchError(f"HTTP {status}", status_code=status)
        assert not (
            is_backfill_range_failure(exc, WhoopFetchError)
            and is_backfill_outage_failure(exc, WhoopFetchError)
        ), status


@pytest.mark.asyncio
async def test_a_skipped_poll_tells_the_run_ledger_it_did_nothing(poll, monkeypatch):
    """The job's return value is what the ledger listener records."""
    from worker.listener import skipped_reason

    poll["cursor"] = datetime.now(UTC) - timedelta(days=10)
    poll["result"] = {"accepted": 0, "rejected": 0, "skipped_no_token": 1}
    job = make_whoop_poll(lambda: _Session())

    assert skipped_reason(await job()) == "no stored token"

    poll["result"] = {"accepted": 3, "rejected": 0}
    assert skipped_reason(await job()) is None
