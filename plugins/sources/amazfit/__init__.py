"""Amazfit / Zepp source plugin — operator-imported token + paginated poll.

Zepp (formerly Huami / Mi Fit) has **no official public API** and the
plaintext-password ``v2/client/login`` flow this plugin was originally
designed against (P6-a, commit ``a3525d8``) was demonstrated dead on
2026-05-22 — the live probe surfaced HTTP 400 + ``error_code 0100``,
and the legacy ``apps-vm-scheduler-1`` Amazfit poll had been silently
500-ing hourly for at least 13h against the same flow.

The community-converged replacement is to NOT run a password login
inside the datahub at all. Operators acquire a fresh ``app_token``
externally (via the maintained ``huami-token`` PyPI CLI, or via a
Zepp-app HTTPS proxy capture per ``zepp-health-cli``) and hand the
token to :mod:`scripts.amazfit_authorize`. Our worker then polls the
``api-mifit-*.zepp.com`` data API with that token; on expiry the
worker fails loud and the operator re-extracts.

Auth flow (H-revise, supersedes P6-a):

  1. Operator runs (externally)
     ``huami-token --method amazfit -e <email> -p <pw> --no_logout``.
  2. Operator pipes that output into ``scripts/amazfit_authorize.py
     --from-huami-token-stdout <file>``, OR directly provides
     ``--from-token <T> --user-id <U> --region <R>``.
  3. The authorize CLI persists the resulting :class:`OAuthToken` via
     :mod:`storage.timescale.oauth_tokens` with provider ``"amazfit"``.
  4. Each worker tick reads the token, hits the data endpoints, and
     stores per-metric rows. No re-login attempts. Plaintext password
     never enters the long-running services.

Status — H-revise scaffold:

  * Manifest declares outbound network + secrets + emit list (secrets
    updated: AMAZFIT_APP_TOKEN + AMAZFIT_USER_ID, no more EMAIL/PASSWORD).
  * AmazfitSource shell raises NotImplementedError on ingest until the
    H-ingest commit lands the fetch + normalize + write loop.
  * :mod:`plugins.sources.amazfit.auth` carries the token-import helpers
    (token_from_app_token_string, token_from_huami_token_output, token_from_env).
  * H-fetch adds the paginated fetchers against ``api-mifit-us3.zepp.com``.
  * H-normalize adds normalizers. H-cli adds the authorize CLI. H-worker wires
    the worker poll job.
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

# Region-keyed base URLs for the Zepp data API. Updated 2026-05-22 from
# api-mifit-us2.huami.com (deprecated) to api-mifit-us3.zepp.com after
# the H-revise probe confirmed the .zepp.com us3 host as the live one.
# eu / cn hosts are best-guess based on personal_stack's 2024 region
# pattern; should be re-verified against live creds in those regions
# before relying on them.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://api-mifit-us3.zepp.com",
    "eu": "https://api-mifit-de.zepp.com",
    "cn": "https://api-mifit.zepp.com",
}

# Headers the data API expects per the H-revise probe + zepp-health-cli.
# ``apptoken`` is added per-call by the fetchers; ``x-request-id`` is
# also added per-call as a fresh UUID. ``r=<uuid>`` query param is
# required on every call and is generated per-call.
DATA_API_HEADERS_BASE: dict[str, str] = {
    "appname": "com.huami.midong",
    "appplatform": "ios_phone",
}


class AmazfitSource(Source):
    """Poll-based Amazfit / Zepp source plugin.

    H-revise ships the scaffold so the manifest discovers, the entrypoint
    resolves, and the token-import helpers can be exercised by tests.
    H-ingest fills in the data-fetch loop.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("amazfit plugin setup complete (H-revise scaffold)")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        raise NotImplementedError(
            "AmazfitSource.ingest is the H-ingest surface. H-revise ships only "
            "the manifest, token-import helpers, and storage scaffolding."
        )

    async def shutdown(self) -> None:
        log.info("amazfit plugin shutdown")


__all__ = [
    "AmazfitSource",
    "DATA_API_HEADERS_BASE",
    "DEVICE_NAME",
    "PROVIDER",
    "REGION_BASE_URLS",
]
