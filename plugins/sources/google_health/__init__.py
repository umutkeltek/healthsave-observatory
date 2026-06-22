"""Google Health API source plugin."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from auth import DEFAULT_OWNER_ID
from plugin_sdk import PluginManifest, Source

from .oauth import GOOGLE_HEALTH_PROVIDER, GoogleHealthOAuthError

DEVICE_NAME = "Google Health"
DEFAULT_LOOKBACK = timedelta(days=7)

log = logging.getLogger("healthsave.plugins.google_health")


class GoogleHealthSource(Source):
    """Poll-based Google Health API source plugin."""

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("google health plugin setup complete")

    async def _load_valid_token(
        self,
        payload: dict[str, Any],
        *,
        session: Any,
        http_client: Any,
        owner_id: Any,
        token_store: Any,
    ):
        from .oauth import GoogleHealthClientConfig, refresh_access_token

        token = await token_store.get_token(
            session,
            provider=GOOGLE_HEALTH_PROVIDER,
            owner_id=owner_id,
        )
        if token is None:
            return None

        if token.is_expired():
            oauth_config = payload.get("oauth_config") or GoogleHealthClientConfig.from_env()
            if not token.refresh_token:
                message = "google health access token expired with no refresh_token stored"
                await token_store.record_refresh_failure(
                    session,
                    provider=GOOGLE_HEALTH_PROVIDER,
                    owner_id=owner_id,
                    error_message=message,
                )
                raise GoogleHealthOAuthError(message)
            try:
                new_token = await refresh_access_token(
                    http_client,
                    oauth_config,
                    refresh_token=token.refresh_token,
                    owner_id=owner_id,
                )
                await token_store.put_token(session, new_token, event_kind="refreshed")
                token = new_token
            except Exception as exc:
                await token_store.record_refresh_failure(
                    session,
                    provider=GOOGLE_HEALTH_PROVIDER,
                    owner_id=owner_id,
                    error_message=str(exc),
                )
                raise

        return token

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        from storage.timescale import oauth_tokens as default_token_store

        from .fetch import fetch_steps
        from .normalize import normalize_step_points

        storage = payload["storage"]
        session = payload["session"]
        http_client = payload["http_client"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)
        since: datetime | None = payload.get("since")
        token_store = payload.get("token_store") or default_token_store

        token = await self._load_valid_token(
            payload,
            session=session,
            http_client=http_client,
            owner_id=owner_id,
            token_store=token_store,
        )
        if token is None:
            log.warning("google health: no stored token owner=%s - skip poll", owner_id)
            return {"accepted": 0, "rejected": 0}

        effective_since = since if since is not None else datetime.now(UTC) - DEFAULT_LOOKBACK
        points = await fetch_steps(
            http_client,
            access_token=token.access_token,
            since=effective_since,
        )
        per_metric = normalize_step_points(points)
        device_id = await storage.get_or_create_device(session, DEVICE_NAME)

        accepted = 0
        for metric, samples in per_metric.items():
            if not samples:
                continue
            written = await storage.ingest_metric(session, device_id, metric, samples, owner_id)
            accepted += written

        log.info(
            "google health poll complete owner=%s accepted=%d since=%s",
            owner_id,
            accepted,
            effective_since.isoformat(),
        )
        return {"accepted": accepted, "rejected": 0}


__all__ = [
    "DEFAULT_LOOKBACK",
    "DEVICE_NAME",
    "GOOGLE_HEALTH_PROVIDER",
    "GoogleHealthSource",
]
