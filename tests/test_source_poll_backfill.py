"""A source poll backfills from its last successful poll after an outage.

Each poll fetched a fixed window ("now minus 1 day" for Whoop and Amazfit,
"now minus 7 days" for Polar and Google), with no record of when a poll last
succeeded. Any outage longer than that window (a dead token, the vendor down,
the worker stopped) left a permanent gap. The worker now keeps a per-provider,
per-owner "last successful poll" cursor and widens the window to cover the gap,
bounded so one poll never asks a vendor for unbounded history.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import worker.sources as worker_sources
from worker.sources import MAX_BACKFILL, make_whoop_poll

from plugins.sources.whoop import DEFAULT_LOOKBACK, WhoopSource


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
    import httpx

    state: dict[str, Any] = {"cursor": None, "recorded": [], "payloads": [], "fail": False}

    async def get_last_successful_poll(session, *, provider, owner_id):
        assert provider == "whoop"
        return state["cursor"]

    async def record_successful_poll(session, *, provider, owner_id, polled_at):
        state["recorded"].append(polled_at)

    cursors = types.ModuleType("storage.timescale.source_poll_cursors")
    cursors.get_last_successful_poll = get_last_successful_poll
    cursors.record_successful_poll = record_successful_poll
    monkeypatch.setitem(sys.modules, "storage.timescale.source_poll_cursors", cursors)

    async def ingest(self, payload):
        state["payloads"].append(payload)
        if state["fail"]:
            raise RuntimeError("whoop is down")
        return {"accepted": 0, "rejected": 0}

    async def no_fusion(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(WhoopSource, "ingest", ingest)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _Http())
    monkeypatch.setattr(worker_sources, "reconcile_source_poll_sessions", no_fusion)

    async def run() -> _Session:
        session = _Session()
        job = make_whoop_poll(lambda: session)
        if state["fail"]:
            with pytest.raises(RuntimeError):
                await job()
        else:
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
