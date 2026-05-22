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

Status — H-ingest:

  * Manifest declares outbound network + secrets + emit list (secrets
    updated: AMAZFIT_APP_TOKEN + AMAZFIT_USER_ID, no more EMAIL/PASSWORD).
  * AmazfitSource.ingest loads the encrypted app_token, fetches paginated
    Zepp data, normalizes rows, and writes through the shared IngestStorage
    protocol.
  * :mod:`plugins.sources.amazfit.auth` carries the token-import helpers
    (token_from_app_token_string, token_from_huami_token_output, token_from_env).
  * H-fetch adds the paginated fetchers against ``api-mifit-us3.zepp.com``.
  * H-normalize adds normalizers. H-cli adds the authorize CLI. H-worker wires
    the worker poll job.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from auth import DEFAULT_OWNER_ID
from plugin_sdk import PluginManifest, Source

log = logging.getLogger("healthsave.plugins.amazfit")

PROVIDER = "amazfit"

# Devices table label written for Amazfit rows. Source-tagged samples
# carry source="Amazfit" so multi-source dashboards split cleanly from
# Apple Watch / Whoop entries.
DEVICE_NAME = "Amazfit"

# How far back to fetch on the first poll (no since= cursor stored yet).
# Mirrors Whoop's DEFAULT_LOOKBACK = 1 day. Operator can override per-call
# via payload["since"].
DEFAULT_LOOKBACK = timedelta(days=1)

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
    """Poll-based Amazfit / Zepp source plugin (H-ingest).

    Each scheduled tick the worker calls :meth:`ingest` with:

      1. ``storage`` — :class:`storage.ports.IngestStorage` for writes.
      2. ``session`` — open ``AsyncSession`` for storage + token store.
      3. ``http_client`` — ``httpx.AsyncClient``-shaped GET surface.
      4. ``owner_id`` (optional) — defaults to ``auth.DEFAULT_OWNER_ID``.
      5. ``since`` (optional) — :class:`datetime` cursor. Defaults to
         "last 24h".
      6. ``token_store`` (optional) — module-like exposing
         ``get_token`` / ``put_token`` / ``record_refresh_failure``.
         Defaults to :mod:`storage.timescale.oauth_tokens`.

    Lifecycle per tick:

      1. ``token_store.get_token(provider="amazfit", owner_id)``.
      2. No token → ``{"accepted": 0, "rejected": 0}`` (no-op until
         the operator runs the authorize CLI).
      3. Expired token → record a ``refresh_failed`` audit event and
         raise :class:`AmazfitAuthError`. Zepp does not issue refresh
         tokens; the recovery primitive is "operator re-runs
         huami-token + the authorize CLI". This is by design — the
         long-running worker never carries the plaintext password.
      4. Compute the time window: explicit ``since`` wins; otherwise
         ``now - 24h``. Day-resolution endpoints (band_data, sport_load)
         use yesterday's date; ms-resolution endpoints use the full
         range.
      5. Fetch heart_rate / spo2_events / stress_events / band_data /
         sport_load. Failures of individual fetchers surface as
         :class:`AmazfitFetchError` and abort the tick (the worker's
         pipeline_runs ledger then marks the run failed).
      6. Normalize each into per-metric sample lists.
      7. ``storage.get_or_create_device("Amazfit")`` → device_id.
      8. ``storage.ingest_metric(...)`` per non-empty metric list,
         carrying ``source="Amazfit"`` so source_id propagates through
         migration 009's columns on ``daily_activity`` and
         ``sleep_sessions``.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("amazfit plugin setup complete")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        from .auth import AmazfitAuthError
        from .fetch import (
            fetch_band_data,
            fetch_heart_rate,
            fetch_spo2_events,
            fetch_sport_load,
            fetch_stress_events,
        )
        from .normalize import (
            normalize_band_data,
            normalize_heart_rate,
            normalize_spo2_events,
            normalize_sport_load,
            normalize_stress_events,
        )

        storage = payload["storage"]
        session = payload["session"]
        http_client = payload["http_client"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)
        since: datetime | None = payload.get("since")

        token_store = payload.get("token_store")
        if token_store is None:
            from storage.timescale import oauth_tokens as token_store  # type: ignore[no-redef]

        # 1. Load token. No token = nothing to do until operator authorizes.
        token = await token_store.get_token(session, provider=PROVIDER, owner_id=owner_id)
        if token is None:
            log.warning("amazfit: no stored token for owner=%s — skip poll", owner_id)
            return {"accepted": 0, "rejected": 0}

        # 2. Expired? Surface as operator-actionable failure.
        if token.is_expired():
            msg = "amazfit token expired — operator must re-extract via huami-token + authorize CLI"
            await token_store.record_refresh_failure(
                session, provider=PROVIDER, owner_id=owner_id, error_message=msg
            )
            raise AmazfitAuthError(msg)

        # 3. Cursor: explicit since= wins; otherwise default 24h lookback.
        effective_since = since if since is not None else datetime.now(UTC) - DEFAULT_LOOKBACK
        now = datetime.now(UTC)
        yesterday = (now - timedelta(days=1)).date()
        today_date = now.date()

        # 4. Fetch. Sequential — daily payload is small (<10KB per call)
        # and parallelizing offers no measurable speedup against Zepp's
        # 5-50ms response times.
        hr_payload = await fetch_heart_rate(
            http_client, token=token, from_time=effective_since, to_time=now
        )
        spo2_payload = await fetch_spo2_events(
            http_client, token=token, from_time=effective_since, to_time=now
        )
        stress_payload = await fetch_stress_events(
            http_client, token=token, from_time=effective_since, to_time=now
        )
        band_payload = await fetch_band_data(http_client, token=token, day=yesterday)
        sport_payload = await fetch_sport_load(
            http_client, token=token, start_day=yesterday, end_day=today_date
        )

        # 5. Normalize. band_data returns three metrics in one call;
        # the rest are single-metric.
        band_norm = normalize_band_data(band_payload)
        per_metric: dict[str, list[dict[str, Any]]] = {}

        def extend(metric: str, rows: list[dict[str, Any]]) -> None:
            if rows:
                per_metric.setdefault(metric, []).extend(rows)

        extend("heart_rate", normalize_heart_rate(hr_payload))
        extend("heart_rate", band_norm["heart_rate"])  # daily max sample
        extend("blood_oxygen", normalize_spo2_events(spo2_payload))
        extend("stress", normalize_stress_events(stress_payload))
        # Daily activity is emitted as per-quantity metric batches —
        # _ingest_daily_quantity rolls each into the matching
        # daily_activity column (steps / distance_m / active_calories).
        extend("step_count", band_norm["step_count"])
        extend("distance_walking_running", band_norm["distance_walking_running"])
        extend("active_energy_burned", band_norm["active_energy_burned"])
        # Sleep is emitted as a single duration quantity sample; v1
        # punts on stage decomposition until Zepp's ``mode`` codes are
        # confirmed against a known night.
        extend("sleep_duration_hours", band_norm["sleep_duration_hours"])
        extend("training_load", normalize_sport_load(sport_payload))

        # 6. Write through the IngestStorage protocol per metric.
        device_id = await storage.get_or_create_device(session, DEVICE_NAME)
        accepted = 0
        for metric, samples in per_metric.items():
            written = await storage.ingest_metric(session, device_id, metric, samples, owner_id)
            accepted += written

        log.info(
            "amazfit poll complete owner=%s accepted=%d metrics=%d since=%s",
            owner_id,
            accepted,
            len(per_metric),
            effective_since.isoformat(),
        )
        return {"accepted": accepted, "rejected": 0}

    async def shutdown(self) -> None:
        log.info("amazfit plugin shutdown")


__all__ = [
    "AmazfitSource",
    "DATA_API_HEADERS_BASE",
    "DEFAULT_LOOKBACK",
    "DEVICE_NAME",
    "PROVIDER",
    "REGION_BASE_URLS",
]
