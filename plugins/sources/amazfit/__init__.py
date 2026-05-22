"""Amazfit / Zepp source plugin — poll-based ingest via huami-token auth.

Zepp (formerly Huami / Mi Fit) has **no official public API**. This plugin
talks to the reverse-engineered cloud endpoints the open-source
``huami-token`` ecosystem uses. The wire shape and even the auth flow
change every 6–12 months at Zepp's discretion. The plugin is designed
so a wire change surfaces as a test failure — but operators should
expect to babysit it.

Auth flow (P6-a scaffold; full impl in P6-d):

  1. POST email + MD5(password) to ``account.huami.com/v2/client/login``
     -> ``token_info.login_token``.
  2. GET ``<region>/v1/user/login/login_check?login_token=<X>``
     -> ``token_info.app_token``.
  3. ``app_token`` used as a bearer-style header on data calls. Lifetime
     ~30 days. Re-login on expiry — there is no separate refresh token.

Auth result is persisted via the same :mod:`storage.timescale.oauth_tokens`
repo Whoop uses (provider=``"amazfit"``). ``refresh_token`` stays NULL
because the refresh primitive is "re-run login with stored
credentials" rather than an OAuth refresh grant.

Status — P6-a scaffold:

  * Manifest declares outbound network + secrets + emit list.
  * AmazfitSource shell raises NotImplementedError on ingest until the
    P6-d commit lands the fetch + normalize + write loop.
  * :mod:`plugins.sources.amazfit.auth` carries the login helpers + the
    AmazfitClientConfig env loader.
  * P6-b adds the paginated fetchers. P6-c adds normalizers. P6-e adds
    a one-time CLI for first login. P6-f wires the worker poll job.
"""

from __future__ import annotations

import logging
from typing import Any

from plugin_sdk import PluginManifest, Source

log = logging.getLogger("healthsave.plugins.amazfit")

PROVIDER = "amazfit"

# Devices table label written for Amazfit rows. Source-tagged samples
# carry source="Amazfit" so multi-source dashboards split cleanly from
# Apple Watch / Whoop entries.
DEVICE_NAME = "Amazfit"

# Region-keyed base URLs for the Zepp data API. Selected at runtime by
# AmazfitClientConfig.from_env reading AMAZFIT_REGION.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://api-mifit-us2.huami.com",
    "eu": "https://api-mifit-de.huami.com",
    "cn": "https://api-mifit.huami.com",
}

AUTH_LOGIN_URL = "https://account.huami.com/v2/client/login"


class AmazfitSource(Source):
    """Poll-based Amazfit / Zepp source plugin.

    P6-a ships the scaffold so the manifest discovers, the entrypoint
    resolves, and the OAuth + auth-helper machinery can be exercised
    by tests. P6-d fills in the data-fetch loop.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("amazfit plugin setup complete (P6-a scaffold)")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        raise NotImplementedError(
            "AmazfitSource.ingest is the P6-d surface. P6-a ships only "
            "the manifest, auth helpers, and token storage scaffolding."
        )

    async def shutdown(self) -> None:
        log.info("amazfit plugin shutdown")


__all__ = [
    "AUTH_LOGIN_URL",
    "AmazfitSource",
    "DEVICE_NAME",
    "PROVIDER",
    "REGION_BASE_URLS",
]
