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
        rejected_access_token: str | None = None,
    ):
        """Return a non-expired OAuthToken or None (no token stored).

        ``rejected_access_token`` is an access token Whoop just answered with
        401: it is refreshed even though it looks unexpired (Whoop sent no
        ``expires_in``, or revoked it early), unless a concurrent caller has
        already stored a different one.

        Token state is committed on its own, before any data is fetched: Whoop
        invalidates the old refresh token the moment a refresh succeeds, so a
        refreshed token rolled back by a later fetch or write failure would
        leave only a dead token stored. A refresh failure is committed too, so
        a dead connector leaves a trace in ``oauth_token_events``.
        """
        from .oauth import (
            WhoopClientConfig,
            WhoopOAuthError,
            refresh_access_token,
        )

        token = await token_store.get_token(session, provider=PROVIDER, owner_id=owner_id)
        if token is None:
            return None

        def needs_refresh(candidate: Any) -> bool:
            return candidate.is_expired() or (
                rejected_access_token is not None
                and candidate.access_token == rejected_access_token
            )

        if needs_refresh(token):
            # Serialize refreshes of this token: a concurrent poll or webhook may
            # already have spent the refresh token. Re-read it under a row lock.
            lock_token = getattr(token_store, "lock_token", None)
            if lock_token is not None:
                token = await lock_token(session, provider=PROVIDER, owner_id=owner_id)
                if token is None or not needs_refresh(token):
                    await session.commit()  # release the lock
                    return token
            if oauth_config is None:
                oauth_config = WhoopClientConfig.from_env()
            if not token.refresh_token:
                msg = "whoop access token expired and no refresh_token stored"
                await token_store.record_refresh_failure(
                    session, provider=PROVIDER, owner_id=owner_id, error_message=msg
                )
                await session.commit()
                raise WhoopOAuthError(msg)
            try:
                new_token = await refresh_access_token(
                    http_client,
                    oauth_config,
                    refresh_token=token.refresh_token,
                    owner_id=owner_id,
                )
                await token_store.put_token(session, new_token, event_kind="refreshed")
                await session.commit()
                token = new_token
            except Exception as e:
                await session.rollback()
                await token_store.record_refresh_failure(
                    session,
                    provider=PROVIDER,
                    owner_id=owner_id,
                    error_message=str(e),
                )
                await session.commit()
                raise

        return token

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        """Pull recent Whoop data and write it through the injected storage.

        Returns ``{"accepted": N, "rejected": 0}``. Rejected is operator-
        side via the existing ``INGEST_REJECTED`` Prometheus counter
        the storage layer bumps when it skips an invalid sample.
        """
        from storage.timescale.observations import default_repository as default_canonical_repo

        from .fetch import (
            WhoopFetchError,
            fetch_body_measurement,
            fetch_cycles,
            fetch_recovery,
            fetch_sleep,
            fetch_workouts,
        )
        from .normalize import (
            canonical_session_observations,
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

        canonical_repository = payload.get("canonical_repository") or default_canonical_repo
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
            # skipped_no_token: nothing was polled, so the worker keeps its cursor.
            return {"accepted": 0, "rejected": 0, "skipped_no_token": 1}

        # 3. Pick a cursor: explicit since= wins; otherwise default lookback.
        effective_since = since if since is not None else datetime.now(UTC) - DEFAULT_LOOKBACK

        # 4. Fetch each resource. Whoop allows parallel calls; sequential
        #    is simpler and the per-day record count is tiny.
        async def fetch_all(access_token: str) -> tuple[Any, ...]:
            return (
                await fetch_recovery(http_client, access_token=access_token, since=effective_since),
                await fetch_sleep(http_client, access_token=access_token, since=effective_since),
                await fetch_workouts(http_client, access_token=access_token, since=effective_since),
                await fetch_cycles(http_client, access_token=access_token, since=effective_since),
                await fetch_body_measurement(http_client, access_token=access_token),
            )

        try:
            fetched = await fetch_all(token.access_token)
        except WhoopFetchError as exc:
            # A 401 on a token we think is valid (no expires_in was sent, or
            # Whoop revoked it early): refresh once and fetch again. Without
            # this the token was never refreshed and every poll failed.
            if exc.status_code != 401 or not token.refresh_token:
                raise
            log.warning("whoop: access token refused (401); refreshing it once")
            token = await self._load_valid_token(
                payload,
                session=session,
                http_client=http_client,
                owner_id=owner_id,
                token_store=token_store,
                oauth_config=oauth_config,
                rejected_access_token=token.access_token,
            )
            if token is None:
                raise
            fetched = await fetch_all(token.access_token)
        recovery_items, sleep_items, workout_items, cycle_items, body_item = fetched

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

        provider_subject_id = (
            token.metadata.get("provider_subject_id")
            or token.metadata.get("whoop_user_id")
            or token.metadata.get("user_id")
        )
        canonical_observations = canonical_session_observations(
            workout_items,
            owner_id=owner_id,
            provider_subject_id=provider_subject_id,
        )
        if canonical_observations:
            accepted += await canonical_repository.insert_many(session, canonical_observations)

        log.info(
            "whoop poll complete owner=%s accepted=%d metrics=%d since=%s",
            owner_id,
            accepted,
            len(per_metric),
            effective_since.isoformat(),
        )
        return {"accepted": accepted, "rejected": 0}

    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, int]:
        """Apply one Whoop webhook event.

        ``*.updated``: fetch the referenced resource and ingest it. If Whoop no
        longer has it (404, deleted since the event was sent) there is nothing
        to ingest, and the event is acknowledged with ``missing: 1``.

        ``*.deleted``: nothing is fetched (the resource is gone). A deleted
        workout's canonical session is marked superseded. The legacy
        per-metric rows a Whoop record wrote carry no Whoop id, so they stay;
        the result's ``deleted`` count says how many canonical rows changed.
        """
        from .fetch import (
            PATH_RECOVERY,
            PATH_SLEEP,
            PATH_WORKOUT,
            WhoopFetchError,
            fetch_one,
        )
        from .normalize import (
            NORMALIZER_ID,
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

        if event_type.endswith(".deleted"):
            deleted = 0
            if normalizer is normalize_workouts:
                from storage.timescale.observations import (
                    default_repository as default_canonical_repo,
                )

                canonical_repository = payload.get("canonical_repository") or (
                    default_canonical_repo
                )
                deleted = await canonical_repository.supersede_source_records(
                    session,
                    owner_id=owner_id,
                    normalizer_id=NORMALIZER_ID,
                    source_record_uids=[str(resource_id)],
                )
            log.info(
                "whoop webhook deletion owner=%s event_type=%s resource_id=%s superseded=%d "
                "(legacy per-metric rows carry no Whoop id and stay)",
                owner_id,
                event_type,
                resource_id,
                deleted,
            )
            return {"accepted": 0, "rejected": 0, "deleted": deleted}

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

        try:
            try:
                data = await fetch_one(
                    http_client, access_token=token.access_token, path=resolved_path
                )
            except WhoopFetchError as exc:
                if exc.status_code != 401 or not token.refresh_token:
                    raise
                log.warning("whoop webhook: access token refused (401); refreshing it once")
                token = await self._load_valid_token(
                    payload,
                    session=session,
                    http_client=http_client,
                    owner_id=owner_id,
                    token_store=token_store,
                    oauth_config=oauth_config,
                    rejected_access_token=token.access_token,
                )
                if token is None:
                    raise
                data = await fetch_one(
                    http_client, access_token=token.access_token, path=resolved_path
                )
        except WhoopFetchError as exc:
            if exc.status_code != 404:
                raise
            log.info(
                "whoop webhook: %s %s is gone (404); nothing to ingest",
                event_type,
                resource_id,
            )
            return {"accepted": 0, "rejected": 0, "missing": 1}
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
