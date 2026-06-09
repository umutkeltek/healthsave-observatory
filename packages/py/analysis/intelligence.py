"""Resolve the effective narrator config from the DB — ADR-0003 D2.

The narrator is configured in two places today: build-time env / a ``config.yaml``
that a redeploy wipes. Migration 017 moves the user-editable posture into the
DB so a UI can change it and it takes effect *without a redeploy*. This module
is the bridge: it reads the owner's :class:`~storage.timescale.intelligence`
rows and folds them onto the env-derived :class:`~analysis.config.LLMConfig`,
producing the config the :class:`~analysis.llm.client.HealthLLMClient` consumes.

Design rules:

* **DB is an overlay, env is the floor.** When the owner has no settings row
  (table empty), ``mode`` is ``off``, or the DB read fails for any reason, the
  resolver returns the env ``base`` unchanged. The narrator must never fail to
  run because the settings table is missing or a query hiccups — the worst case
  is "behave like before the UI existed". Defensive by design so the per-job
  reload is safe to ship before the table is even applied live.
* **``mode`` is the master switch.** Cloud egress is permitted only when
  ``mode == 'cloud'`` AND the explicit opt-in is set; ``mode == 'local'`` forces
  ``allow_cloud_egress`` off no matter what the column says. The egress gate
  re-checks the route per candidate at send time (defense in depth) — this just
  makes the resolved config honest about intent.
* **Storage is imported lazily** (like ``analysis.engine``) to keep the
  cross-package import graph cold until a resolve actually happens.
"""

from __future__ import annotations

import logging
from uuid import UUID

from auth import DEFAULT_OWNER_ID

from .config import LLMConfig, LLMFallbackEntry

log = logging.getLogger("healthsave.analysis")


async def resolve_llm_config(
    session,
    *,
    base: LLMConfig,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> LLMConfig:
    """Return the effective :class:`LLMConfig`: ``base`` overlaid with DB settings.

    ``session`` is an ``AsyncSession`` already in scope at the call site (the
    engine opens one per job). On any storage error, or when the owner is
    unconfigured / ``mode == 'off'``, ``base`` is returned verbatim.
    """
    from storage.timescale import intelligence as repo  # lazy: cold until resolve

    try:
        settings = await repo.get_settings(session, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 - never let config-read break narration
        log.warning("intelligence: settings read failed (%s); using env config", exc)
        return base

    if settings is None or settings.mode == "off":
        return base
    if settings.primary_connection_id is None:
        log.info("intelligence: mode=%s but no primary connection; using env config", settings.mode)
        return base

    try:
        primary = await repo.get_connection(
            session, connection_id=settings.primary_connection_id, owner_id=owner_id
        )
        if primary is None or not primary.enabled:
            return base
        primary_key = (
            await repo.get_connection_secret(session, connection_id=primary.id, owner_id=owner_id)
            if primary.credential_id is not None
            else None
        )
        fallback = await _resolve_fallback(session, repo, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 - same fail-safe as above
        log.warning("intelligence: connection resolve failed (%s); using env config", exc)
        return base

    # mode is the master switch: only mode='cloud' + opt-in permits egress.
    allow_cloud = settings.mode == "cloud" and bool(settings.allow_cloud_egress)

    return base.model_copy(
        update={
            "provider": primary.provider,
            "model": settings.primary_model or base.model,
            "base_url": primary.base_url or base.base_url,
            "api_key": primary_key or "",
            "temperature": (
                settings.primary_temperature
                if settings.primary_temperature is not None
                else base.temperature
            ),
            "max_tokens": (
                settings.primary_max_tokens
                if settings.primary_max_tokens is not None
                else base.max_tokens
            ),
            "allow_cloud_egress": allow_cloud,
            "redact_cloud_prompts": bool(settings.redact_cloud_prompts),
            "fallback": fallback,
        }
    )


async def _resolve_fallback(session, repo, *, owner_id: UUID) -> list[LLMFallbackEntry]:
    """Build self-describing fallback entries from the owner's route chain.

    Each route names a connection; we attach that connection's provider /
    base_url / decrypted key so the narrator candidate is fully specified and
    the egress gate can classify it. Disabled connections and routes whose
    connection vanished are skipped (the chain stays contiguous).
    """
    routes = await repo.get_fallback_routes(session, owner_id=owner_id)
    if not routes:
        return []
    # Resolve each route's connection once; cache to avoid re-querying a shared one.
    conn_cache: dict[int, object] = {}
    entries: list[LLMFallbackEntry] = []
    for route in routes:
        conn = conn_cache.get(route.connection_id)
        if conn is None:
            conn = await repo.get_connection(
                session, connection_id=route.connection_id, owner_id=owner_id
            )
            if conn is not None:
                conn_cache[route.connection_id] = conn
        if conn is None or not conn.enabled:
            continue
        key = (
            await repo.get_connection_secret(session, connection_id=conn.id, owner_id=owner_id)
            if conn.credential_id is not None
            else None
        )
        entries.append(
            LLMFallbackEntry(
                provider=conn.provider,
                model=route.model,
                base_url=conn.base_url,
                api_key=key,
            )
        )
    return entries
