"""Process-level stale-while-revalidate cache for expensive v2 reads.

The canonical-coverage and source-attribution aggregates walk the whole
canonical store (2M+ rows live). They are correct but heavy, and three
surfaces want them (readiness, receipts, the dashboard's poll cadence).
Fix at the source: serve a cached aggregate and refresh it at most once
per TTL, so the scan cost is paid once a minute instead of per request.

Semantics (mirrors apps/web ``lib/ttlCache.ts``):
- cold key → fetch inline (the first request after boot pays the scan);
- fresh key → cached value, no DB touch;
- stale key → the first caller refreshes inline, concurrent callers get
  the stale value immediately (single-flight via the ``refreshing`` flag);
- refresh failure → log + serve the stale value (a dashboard aggregate a
  minute old beats a 500), unless there is nothing cached yet.

Single-process state — each API worker keeps its own copy, which is fine
for a self-hosted single-user deployment. Not a correctness boundary:
every value here is re-derivable from the store at any time.
"""

from __future__ import annotations

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
            if (now - entry.fetched_at) < ttl or entry.refreshing:
                return entry.value
            entry.refreshing = True
            try:
                value = await fetcher()
            except Exception:
                # Serve the stale aggregate rather than failing the read;
                # the next request retries the refresh.
                entry.refreshing = False
                log.warning("swr refresh failed for %r; serving stale value", key, exc_info=True)
                return entry.value
            self._entries[key] = _Entry(value=value, fetched_at=time.monotonic())
            return value

        value = await fetcher()
        self._entries[key] = _Entry(value=value, fetched_at=time.monotonic())
        return value

    def clear(self) -> None:
        """Drop every entry (tests; or after writes that must be visible now)."""
        self._entries.clear()


# The shared instance for the v2 read surfaces. Keys in use:
#   "canonical_coverage" — fetch_canonical_coverage (readiness)
#   "canonical_sources"  — fetch_canonical_sources (readiness + receipts)
v2_read_cache = SwrCache()
