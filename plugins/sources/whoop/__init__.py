"""Whoop source plugin — poll-based ingest of recovery / sleep / workout / cycle / body data.

Each scheduled tick the worker calls :meth:`WhoopSource.ingest` with:

  1. ``storage`` — :class:`storage.ports.IngestStorage` instance for writes.
  2. ``session`` — open ``AsyncSession`` for both storage + token store.
  3. ``http_client`` — ``httpx.AsyncClient``-shaped GET/POST surface.
  4. ``owner_id`` (optional) — defaults to ``auth.DEFAULT_OWNER_ID``.
  5. ``since`` (optional) — :class:`datetime` cursor. Defaults to "last 24h".
  6. ``token_store`` (optional) — module-like object exposing
     ``get_token`` / ``put_token`` / ``record_refresh_failure``. Defaults
     to :mod:`storage.timescale.oauth_tokens`.
  7. ``oauth_config`` (optional) — :class:`WhoopClientConfig`. Defaults
     to ``WhoopClientConfig.from_env()``.

ingest reads the stored token, refreshes if expired (atomically — Whoop
invalidates the previous refresh_token on success), then fetches
recovery / sleep / workouts / cycles and body measurement, normalizes
each into existing IngestStorage sample shapes, and writes via the
injected ``storage.ingest_metric`` Protocol method.

Failure modes:

  * No token stored: log and return ``{"accepted": 0, "rejected": 0}``.
    The poll is a no-op until the operator runs the authorize CLI.
  * Refresh failure: a ``refresh_failed`` audit event is recorded
    (operator-visible) and the underlying exception is re-raised so
    the worker's pipeline_runs ledger marks the run as failed.
  * Fetch failure: re-raised; same ledger semantics.
  * Per-metric write failure: ``storage.ingest_metric`` is expected to
    skip invalid samples rather than fail the whole batch (existing
    contract with the Apple plugin); we mirror it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from auth import DEFAULT_OWNER_ID
from plugin_sdk import PluginManifest, Source

log = logging.getLogger("healthsave.plugins.whoop")

PROVIDER = "whoop"
API_BASE = "https://api.prod.whoop.com"
OAUTH_AUTH_URL = f"{API_BASE}/oauth/oauth2/auth"
OAUTH_TOKEN_URL = f"{API_BASE}/oauth/oauth2/token"

# Default device label written into the devices table for Whoop rows.
# Source-tagged samples ALSO carry source='Whoop' so multi-source
# dashboards can split, but the device_id is what TimescaleDB's
# dedup unique indexes key on so we keep it stable.
DEVICE_NAME = "Whoop"

# How far back to fetch on the first poll (no since= cursor stored yet).
DEFAULT_LOOKBACK = timedelta(days=1)

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

    P2: full end-to-end ingest. Token refresh + paginated fetch +
    normalize + IngestStorage write. The worker calls this each tick;
    a future admin endpoint will trigger an on-demand poll.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("whoop plugin setup complete")

    async def _load_valid_token(
        self,
        payload: dict[str, Any],
        *,
        session: Any,
        http_client: Any,
        owner_id: Any,
        token_store: Any,
        oauth_config: Any,
    ):
        """Return a non-expired OAuthToken or None (no token stored)."""
        from .oauth import (
            WhoopClientConfig,
            WhoopOAuthError,
            refresh_access_token,
        )

        token = await token_store.get_token(session, provider=PROVIDER, owner_id=owner_id)
        if token is None:
            return None

        if token.is_expired():
            if oauth_config is None:
                oauth_config = WhoopClientConfig.from_env()
            if not token.refresh_token:
                msg = "whoop access token expired and no refresh_token stored"
                await token_store.record_refresh_failure(
                    session, provider=PROVIDER, owner_id=owner_id, error_message=msg
                )
                raise WhoopOAuthError(msg)
            try:
                new_token = await refresh_access_token(
                    http_client,
                    oauth_config,
                    refresh_token=token.refresh_token,
                    owner_id=owner_id,
                )
                await token_store.put_token(session, new_token, event_kind="refreshed")
                token = new_token
            except Exception as e:
                await token_store.record_refresh_failure(
                    session,
                    provider=PROVIDER,
                    owner_id=owner_id,
                    error_message=str(e),
                )
                raise

        return token

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        """Pull recent Whoop data and write it through the injected storage.

        Returns ``{"accepted": N, "rejected": 0}``. Rejected is operator-
        side via the existing ``INGEST_REJECTED`` Prometheus counter
        the storage layer bumps when it skips an invalid sample.
        """
        from .fetch import (
            fetch_body_measurement,
            fetch_cycles,
            fetch_recovery,
            fetch_sleep,
            fetch_workouts,
        )
        from .normalize import (
            normalize_body_measurement,
            normalize_cycles,
            normalize_recovery,
            normalize_sleep,
            normalize_workouts,
        )
        from .oauth import WhoopClientConfig

        storage = payload["storage"]
        session = payload["session"]
        http_client = payload["http_client"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)
        since: datetime | None = payload.get("since")

        token_store = payload.get("token_store")
        if token_store is None:
            from storage.timescale import oauth_tokens as token_store  # type: ignore[no-redef]

        oauth_config: WhoopClientConfig | None = payload.get("oauth_config")

        # 1. Load token. No token = nothing to do until operator authorizes.
        token = await self._load_valid_token(
            payload,
            session=session,
            http_client=http_client,
            owner_id=owner_id,
            token_store=token_store,
            oauth_config=oauth_config,
        )
        if token is None:
            log.warning("whoop: no stored token for owner=%s — skip poll", owner_id)
            return {"accepted": 0, "rejected": 0}

        # 3. Pick a cursor: explicit since= wins; otherwise default lookback.
        effective_since = since if since is not None else datetime.now(UTC) - DEFAULT_LOOKBACK

        # 4. Fetch each resource. Whoop allows parallel calls; sequential
        #    is simpler and the per-day record count is tiny.
        access_token = token.access_token
        recovery_items = await fetch_recovery(
            http_client, access_token=access_token, since=effective_since
        )
        sleep_items = await fetch_sleep(
            http_client, access_token=access_token, since=effective_since
        )
        workout_items = await fetch_workouts(
            http_client, access_token=access_token, since=effective_since
        )
        cycle_items = await fetch_cycles(
            http_client, access_token=access_token, since=effective_since
        )
        body_item = await fetch_body_measurement(http_client, access_token=access_token)

        # 5. Normalize each into per-metric sample lists.
        per_metric: dict[str, list[dict[str, Any]]] = {}
        for normalized in (
            normalize_recovery(recovery_items),
            normalize_sleep(sleep_items),
            normalize_workouts(workout_items),
            normalize_cycles(cycle_items),
            normalize_body_measurement(body_item or {}),
        ):
            for metric, samples in normalized.items():
                if samples:
                    per_metric.setdefault(metric, []).extend(samples)

        # 6. Route each metric's samples through the IngestStorage protocol.
        device_id = await storage.get_or_create_device(session, DEVICE_NAME)
        accepted = 0
        for metric, samples in per_metric.items():
            written = await storage.ingest_metric(session, device_id, metric, samples, owner_id)
            accepted += written

        log.info(
            "whoop poll complete owner=%s accepted=%d metrics=%d since=%s",
            owner_id,
            accepted,
            len(per_metric),
            effective_since.isoformat(),
        )
        return {"accepted": accepted, "rejected": 0}

    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, int]:
        """Fetch + ingest the single Whoop resource referenced by a webhook event."""
        from .fetch import (
            PATH_RECOVERY,
            PATH_SLEEP,
            PATH_WORKOUT,
            fetch_one,
        )
        from .normalize import (
            normalize_recovery,
            normalize_sleep,
            normalize_workouts,
        )
        from .oauth import WhoopClientConfig

        event = payload["event"]
        event_type = event.get("type") if isinstance(event, dict) else None
        resource_id = event.get("id") if isinstance(event, dict) else None
        if not isinstance(event_type, str) or not resource_id:
            raise ValueError("whoop webhook event missing type/id")

        resolved_path: str | None = None
        normalizer = None
        if "recovery" in event_type:
            resolved_path = f"{PATH_RECOVERY}/{resource_id}"
            normalizer = normalize_recovery
        elif "sleep" in event_type:
            resolved_path = f"{PATH_SLEEP}/{resource_id}"
            normalizer = normalize_sleep
        elif "workout" in event_type:
            resolved_path = f"{PATH_WORKOUT}/{resource_id}"
            normalizer = normalize_workouts
        else:
            return {"accepted": 0, "rejected": 0}

        storage = payload["storage"]
        session = payload["session"]
        http_client = payload["http_client"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)

        token_store = payload.get("token_store")
        if token_store is None:
            from storage.timescale import oauth_tokens as token_store  # type: ignore[no-redef]

        oauth_config: WhoopClientConfig | None = payload.get("oauth_config")
        token = await self._load_valid_token(
            payload,
            session=session,
            http_client=http_client,
            owner_id=owner_id,
            token_store=token_store,
            oauth_config=oauth_config,
        )
        if token is None:
            log.warning("whoop webhook: no stored token for owner=%s — skip event", owner_id)
            return {"accepted": 0, "rejected": 0}

        data = await fetch_one(http_client, access_token=token.access_token, path=resolved_path)
        normalized = normalizer([data])
        device_id = await storage.get_or_create_device(session, DEVICE_NAME)
        accepted = 0
        for metric, samples in normalized.items():
            if samples:
                accepted += await storage.ingest_metric(
                    session, device_id, metric, samples, owner_id
                )

        log.info(
            "whoop webhook complete owner=%s accepted=%d event_type=%s resource_id=%s",
            owner_id,
            accepted,
            event_type,
            resource_id,
        )
        return {"accepted": accepted, "rejected": 0}

    async def shutdown(self) -> None:
        log.info("whoop plugin shutdown")


__all__ = [
    "API_BASE",
    "DEFAULT_LOOKBACK",
    "DEFAULT_SCOPES",
    "DEVICE_NAME",
    "OAUTH_AUTH_URL",
    "OAUTH_TOKEN_URL",
    "PROVIDER",
    "WhoopSource",
]
