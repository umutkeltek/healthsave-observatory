"""Whoop source plugin — poll-based ingest of recovery / sleep / workout / cycle data.

Each scheduled tick (P2 worker job, not in P1) the plugin:

  1. Reads the stored OAuth token via :mod:`storage.timescale.oauth_tokens`.
  2. Refreshes the access token if it has expired (or is within the
     refresh-ahead leeway).
  3. Fetches recent recovery / sleep / workout / cycle pages from
     Whoop's developer API.
  4. Normalizes each into the same row shapes the Apple plugin emits,
     so storage routes them into existing tables
     (``heart_rate``, ``hrv``, ``sleep_sessions``, ``workouts``).

Status — P1 scaffold:

  * Manifest + OAuth helpers + token store integration shipped.
  * :meth:`WhoopSource.ingest` raises :class:`NotImplementedError`
    so the worker scheduler will refuse to drive a half-built source
    if a misconfiguration accidentally enables it.
  * P2 adds :mod:`plugins.sources.whoop.fetch` + a worker job
    registration + the CLI/admin endpoint that walks the
    authorization-code flow.
"""

from __future__ import annotations

import logging
from typing import Any

from plugin_sdk import PluginManifest, Source

log = logging.getLogger("healthsave.plugins.whoop")

PROVIDER = "whoop"
API_BASE = "https://api.prod.whoop.com"
OAUTH_AUTH_URL = f"{API_BASE}/oauth/oauth2/auth"
OAUTH_TOKEN_URL = f"{API_BASE}/oauth/oauth2/token"

# Default scopes — "offline" is required to receive a refresh_token.
DEFAULT_SCOPES: tuple[str, ...] = (
    "read:profile",
    "read:body_measurement",
    "read:recovery",
    "read:sleep",
    "read:cycles",
    "read:workout",
    "offline",
)


class WhoopSource(Source):
    """Poll-based Whoop source plugin.

    P1 ships the scaffold so the manifest is discoverable, the
    entrypoint resolves, and the OAuth + token-store machinery can be
    exercised by tests. P2 fills in the data-fetch loop.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("whoop plugin setup complete (P1 scaffold)")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        raise NotImplementedError(
            "WhoopSource.ingest is the P2 surface. P1 ships only the manifest, "
            "OAuth helpers, and token storage scaffolding."
        )

    async def shutdown(self) -> None:
        log.info("whoop plugin shutdown")


__all__ = [
    "API_BASE",
    "DEFAULT_SCOPES",
    "OAUTH_AUTH_URL",
    "OAUTH_TOKEN_URL",
    "PROVIDER",
    "WhoopSource",
]
