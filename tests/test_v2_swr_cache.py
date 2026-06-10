"""Tests for the process-level SWR cache behind /api/v2/readiness + /receipts.

Pure asyncio — no DB, no routes. The route-level behavior (one scan per TTL
instead of per request) follows from these semantics plus the shared keys.
"""

from __future__ import annotations

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
async def test_stale_value_triggers_refresh(monkeypatch):
    cache = SwrCache()
    counter = _Counter()
    await cache.get("k", counter.fetch, ttl_seconds=60)

    # Age the entry past the TTL without real sleeping.
    cache._entries["k"].fetched_at -= 120

    refreshed = await cache.get("k", counter.fetch, ttl_seconds=60)
    assert refreshed == 2
    assert counter.calls == 2


@pytest.mark.asyncio
async def test_refresh_failure_serves_stale_value():
    cache = SwrCache()
    ok = _Counter()
    await cache.get("k", ok.fetch, ttl_seconds=60)
    cache._entries["k"].fetched_at -= 120

    failing = _Counter(error=RuntimeError("db down"))
    served = await cache.get("k", failing.fetch, ttl_seconds=60)
    assert served == 1  # the stale value, not a raise
    assert failing.calls == 1
    # The failed refresh resets the flag so the next caller retries.
    assert cache._entries["k"].refreshing is False


@pytest.mark.asyncio
async def test_cold_fetch_failure_propagates():
    cache = SwrCache()
    failing = _Counter(error=RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        await cache.get("k", failing.fetch, ttl_seconds=60)


@pytest.mark.asyncio
async def test_concurrent_callers_get_stale_while_refreshing():
    """While one caller refreshes a stale key, others ride the stale value
    instead of stacking duplicate scans (single-flight)."""
    import asyncio

    cache = SwrCache()
    seed = _Counter()
    await cache.get("k", seed.fetch, ttl_seconds=60)
    cache._entries["k"].fetched_at -= 120

    release = asyncio.Event()
    slow_calls = 0

    async def slow_fetch():
        nonlocal slow_calls
        slow_calls += 1
        await release.wait()
        return 99

    refresher = asyncio.create_task(cache.get("k", slow_fetch, ttl_seconds=60))
    await asyncio.sleep(0)  # let the refresher enter the fetch
    rider = await cache.get("k", slow_fetch, ttl_seconds=60)
    assert rider == 1  # stale value, no second scan started
    release.set()
    assert await refresher == 99
    assert slow_calls == 1


def test_clear_drops_entries():
    cache = SwrCache()
    cache._entries["k"] = object()  # type: ignore[assignment]
    cache.clear()
    assert cache._entries == {}
