"""Polar AccessLink source plugin."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from auth import DEFAULT_OWNER_ID
from plugin_sdk import PluginManifest, Source

from .oauth import POLAR_PROVIDER, PolarOAuthError

DEVICE_NAME = "Polar"
DEFAULT_LOOKBACK = timedelta(days=7)

log = logging.getLogger("healthsave.plugins.polar")


class PolarSource(Source):
    """Poll-based Polar AccessLink source plugin."""

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def setup(self, config: dict[str, Any]) -> None:
        log.info("polar plugin setup complete")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        from storage.timescale import oauth_tokens as default_token_store

        from .fetch import fetch_exercises
        from .normalize import normalize_exercises

        storage = payload["storage"]
        session = payload["session"]
        http_client = payload["http_client"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)
        since: datetime | None = payload.get("since")
        token_store = payload.get("token_store") or default_token_store

        token = await token_store.get_token(session, provider=POLAR_PROVIDER, owner_id=owner_id)
        if token is None:
            log.warning("polar: no stored token owner=%s - skip poll", owner_id)
            return {"accepted": 0, "rejected": 0}
        if token.is_expired():
            message = "polar access token unexpectedly expired"
            if hasattr(token_store, "record_refresh_failure"):
                await token_store.record_refresh_failure(
                    session, provider=POLAR_PROVIDER, owner_id=owner_id, error_message=message
                )
            raise PolarOAuthError(message)

        effective_since = since if since is not None else datetime.now(UTC) - DEFAULT_LOOKBACK
        exercises = await fetch_exercises(
            http_client,
            access_token=token.access_token,
            since=effective_since,
        )
        per_metric = normalize_exercises(exercises)
        device_id = await storage.get_or_create_device(session, DEVICE_NAME)

        accepted = 0
        for metric, samples in per_metric.items():
            if not samples:
                continue
            written = await storage.ingest_metric(session, device_id, metric, samples, owner_id)
            accepted += int(written)

        log.info(
            "polar poll complete owner=%s accepted=%d metrics=%d since=%s",
            owner_id,
            accepted,
            len(per_metric),
            effective_since.isoformat(),
        )
        return {"accepted": accepted, "rejected": 0}

    async def shutdown(self) -> None:
        log.info("polar plugin shutdown")


__all__ = ["DEVICE_NAME", "POLAR_PROVIDER", "PolarSource"]
