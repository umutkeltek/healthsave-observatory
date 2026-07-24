"""Tests for the process-level SWR cache behind /api/v2/readiness + /receipts.

Pure asyncio — no DB, no routes. The route-level behavior (one scan per TTL
instead of per request) follows from these semantics plus the shared keys.

Semantics under test (true stale-while-revalidate, matching apps/web
``lib/ttlCache.ts``): a stale hit returns the cached value IMMEDIATELY and
schedules exactly one detached background refresh (single-flight via the
``refreshing`` flag); no caller ever awaits the fetcher on a stale hit, only
on a cold miss.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.swr import SwrCache  # noqa: E402


class _Counter:
    def __init__(self, values=None, error: Exception | None = None):
        self.calls = 0
        self._values = list(values or [])
        self._error = error

    async def fetch(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._values.pop(0) if self._values else self.calls


def _only_task(cache: SwrCache) -> asyncio.Task:
    """The single background refresh task a stale hit just scheduled."""
    (task,) = cache._background_tasks
    return task


@pytest.mark.asyncio
async def test_fresh_value_served_without_refetch():
    cache = SwrCache()
    counter = _Counter()
    first = await cache.get("k", counter.fetch, ttl_seconds=60)
    second = await cache.get("k", counter.fetch, ttl_seconds=60)
    assert first == second == 1
    assert counter.calls == 1


@pytest.mark.asyncio
async def test_zero_ttl_disables_caching():
    cache = SwrCache()
    counter = _Counter()
    assert await cache.get("k", counter.fetch, ttl_seconds=0) == 1
    assert await cache.get("k", counter.fetch, ttl_seconds=0) == 2
    assert counter.calls == 2


@pytest.mark.asyncio
async def test_cold_fetch_failure_propagates():
    cache = SwrCache()
    failing = _Counter(error=RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        await cache.get("k", failing.fetch, ttl_seconds=60)


def test_clear_drops_entries():
    cache = SwrCache()
    cache._entries["k"] = object()  # type: ignore[assignment]
    cache.clear()
    assert cache._entries == {}


@pytest.mark.asyncio
async def test_stale_hit_returns_stale_value_without_blocking_on_the_fetcher():
    """The defining SWR property: a stale hit never awaits the fetcher inline."""
    cache = SwrCache()
    seed = _Counter()
    await cache.get("k", seed.fetch, ttl_seconds=60)
    cache._entries["k"].fetched_at -= 120

    block = asyncio.Event()

    async def slow_fetch():
        await block.wait()
        return 999

    # If this awaited the fetcher inline it would hang forever (block is never
    # set before the timeout), so wrapping in wait_for proves it doesn't.
    served = await asyncio.wait_for(cache.get("k", slow_fetch, ttl_seconds=60), timeout=1)
    assert served == 1  # the stale value, not the refreshed one
    assert cache._entries["k"].refreshing is True

    # Let the background refresh finish so it doesn't leak into the next test.
    block.set()
    await _only_task(cache)


@pytest.mark.asyncio
async def test_stale_refresh_lands_in_background_then_fresh_value_is_served():
    cache = SwrCache()
    counter = _Counter()
    await cache.get("k", counter.fetch, ttl_seconds=60)  # seed: calls == 1
    cache._entries["k"].fetched_at -= 120

    stale = await cache.get("k", counter.fetch, ttl_seconds=60)
    assert stale == 1  # still stale — the refresh hasn't landed yet

    await _only_task(cache)  # let the scheduled background refresh complete

    fresh = await cache.get("k", counter.fetch, ttl_seconds=60)
    assert fresh == 2
    assert counter.calls == 2
    assert cache._entries["k"].refreshing is False


@pytest.mark.asyncio
async def test_refresh_failure_serves_stale_value_and_resets_flag_for_retry():
    cache = SwrCache()
    ok = _Counter()
    await cache.get("k", ok.fetch, ttl_seconds=60)
    cache._entries["k"].fetched_at -= 120

    failing = _Counter(error=RuntimeError("db down"))
    served = await cache.get("k", failing.fetch, ttl_seconds=60)
    assert served == 1  # the stale value, not a raise

    await _only_task(cache)  # let the failing background refresh finish

    assert failing.calls == 1
    assert cache._entries["k"].value == 1  # still the stale value
    # The failed refresh resets the flag so the next stale hit retries.
    assert cache._entries["k"].refreshing is False

    cache._entries["k"].fetched_at -= 120
    retry = _Counter()
    served_again = await cache.get("k", retry.fetch, ttl_seconds=60)
    assert served_again == 1  # still the last-known-good value while it retries
    assert cache._entries["k"].refreshing is True
    await _only_task(cache)
    assert retry.calls == 1


@pytest.mark.asyncio
async def test_single_flight_two_stale_hits_trigger_exactly_one_background_fetch():
    """Two stale hits in quick succession must not stack duplicate scans."""
    cache = SwrCache()
    counter = _Counter()
    await cache.get("k", counter.fetch, ttl_seconds=60)  # seed: calls == 1
    cache._entries["k"].fetched_at -= 120

    first = await cache.get("k", counter.fetch, ttl_seconds=60)
    second = await cache.get("k", counter.fetch, ttl_seconds=60)
    assert first == second == 1  # both ride the same stale value
    assert cache._entries["k"].refreshing is True
    assert len(cache._background_tasks) == 1  # only one refresh was scheduled

    await _only_task(cache)
    assert counter.calls == 2  # the seed fetch + exactly one background refresh
