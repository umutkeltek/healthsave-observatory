"""Process-level stale-while-revalidate cache for expensive v2 reads.

The canonical-coverage and source-attribution aggregates walk the whole
canonical store (2M+ rows live). They are correct but heavy, and three
surfaces want them (readiness, receipts, the dashboard's poll cadence).
Fix at the source: serve a cached aggregate and refresh it at most once
per TTL, so the scan cost is paid once a minute instead of per request.

Semantics (mirrors apps/web ``lib/ttlCache.ts``):
- cold key → fetch inline (the first request after boot pays the scan);
- fresh key → cached value, no DB touch;
- stale key → the stale value is returned IMMEDIATELY and a single
  background refresh is scheduled (single-flight via the ``refreshing``
  flag) that swaps in the fresh value when it lands; no caller ever
  blocks on the fetcher for a stale hit, not even the one that triggers
  the refresh;
- refresh failure → log + keep serving the already-cached stale value,
  and reset ``refreshing`` so a later stale hit retries (a cold miss has
  nothing to fall back to, so it still propagates the error).

Single-process state — each API worker keeps its own copy, which is fine
for a self-hosted single-user deployment. Not a correctness boundary:
every value here is re-derivable from the store at any time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("healthsave.api.swr")

# One knob: how long a cached aggregate counts as fresh. 0 disables caching
# (every request fetches), which is also the simplest test posture.
DEFAULT_TTL_SECONDS = float(os.environ.get("V2_READ_CACHE_TTL_SECONDS", "60"))


@dataclass
class _Entry:
    value: Any
    fetched_at: float
    refreshing: bool = field(default=False)


class SwrCache:
    """Keyed stale-while-revalidate cache; see module docstring for semantics."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        # Strong refs to in-flight background refreshes — asyncio only holds a
        # weak ref to a scheduled task, so without this a refresh can be
        # garbage-collected mid-flight (a well-known asyncio.create_task trap).
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def get(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: float | None = None,
    ) -> Any:
        ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return await fetcher()

        entry = self._entries.get(key)
        now = time.monotonic()

        if entry is not None:
            if (now - entry.fetched_at) < ttl:
                return entry.value
            if not entry.refreshing:
                entry.refreshing = True
                self._spawn_refresh(key, fetcher)
            # Stale — whether this call just scheduled the refresh or one is
            # already in flight, serve the last-known-good value now. Never
            # await the fetcher on this path.
            return entry.value

        value = await fetcher()
        self._entries[key] = _Entry(value=value, fetched_at=time.monotonic())
        return value

    def _spawn_refresh(self, key: str, fetcher: Callable[[], Awaitable[Any]]) -> None:
        task = asyncio.create_task(self._refresh(key, fetcher))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _refresh(self, key: str, fetcher: Callable[[], Awaitable[Any]]) -> None:
        try:
            value = await fetcher()
        except Exception:
            log.warning("swr refresh failed for %r; serving stale value", key, exc_info=True)
            stale = self._entries.get(key)
            if stale is not None:
                # Reset the flag (not the value) so a later stale hit retries;
                # the aggregate cached here is still the last-known-good one.
                stale.refreshing = False
            return
        self._entries[key] = _Entry(value=value, fetched_at=time.monotonic())

    def clear(self) -> None:
        """Drop every entry (tests; or after writes that must be visible now)."""
        self._entries.clear()


# The shared instance for the v2 read surfaces. Keys in use:
#   "canonical_coverage" — fetch_canonical_coverage (readiness)
#   "canonical_sources"  — fetch_canonical_sources (readiness + receipts)
v2_read_cache = SwrCache()
