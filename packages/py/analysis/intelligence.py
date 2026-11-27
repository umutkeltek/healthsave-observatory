"""Resolve the effective narrator config from the DB — ADR-0003 D2.

The narrator is configured in two places today: build-time env / a ``config.yaml``
that a redeploy wipes. Migration 017 moves the user-editable posture into the
DB so a UI can change it and it takes effect *without a redeploy*. This module
is the bridge: it reads the owner's :class:`~storage.timescale.intelligence`
rows and folds them onto the env-derived :class:`~analysis.config.LLMConfig`,
producing the config the :class:`~analysis.llm.client.HealthLLMClient` consumes.

Design rules:

* **DB is an overlay, env is the floor.** When the owner has no settings row
  (table empty), ``mode`` is ``off``, or the settings table does not exist
  yet, the resolver returns the env ``base`` unchanged: the UI has not taken
  over, so the env (including its cloud-egress opt-in) is what the operator
  chose. The narrator must never fail to run because of a missing table or a
  query hiccup.
* **Fail closed on cloud egress.** Once the UI may have taken over (a settings
  row with ``mode`` local/cloud, or a read that failed so we cannot tell), the
  env's cloud-egress opt-in is no longer the person's decision: they may have
  chosen local, revoked consent, or consented only to a different
  destination. Every fallback to ``base`` on those paths therefore turns
  cloud egress off; local narration still runs.
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
        if _is_undefined_table(exc):
            # Before migration 017: the UI cannot have been used.
            return base
        log.warning(
            "intelligence: settings read failed (%s); using env config without cloud egress",
            exc,
        )
        return _without_cloud_egress(base)

    if settings is None or settings.mode == "off":
        return base
    if settings.primary_connection_id is None:
        log.info("intelligence: mode=%s but no primary connection; using env config", settings.mode)
        return _without_cloud_egress(base)

    try:
        primary = await repo.get_connection(
            session, connection_id=settings.primary_connection_id, owner_id=owner_id
        )
        if primary is None or not primary.enabled:
            return _without_cloud_egress(base)
        primary_key = (
            await repo.get_connection_secret(session, connection_id=primary.id, owner_id=owner_id)
            if primary.credential_id is not None
            else None
        )
        fallback = await _resolve_fallback(session, repo, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 - same fail-safe as above
        log.warning(
            "intelligence: connection resolve failed (%s); using env config without cloud egress",
            exc,
        )
        return _without_cloud_egress(base)

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


def _without_cloud_egress(base: LLMConfig) -> LLMConfig:
    """``base`` with its cloud-egress opt-in withdrawn (``base`` itself if already off)."""
    if not base.allow_cloud_egress:
        return base
    return base.model_copy(update={"allow_cloud_egress": False})


def _is_undefined_table(exc: BaseException) -> bool:
    """True when ``exc`` (or its cause chain) is PostgreSQL's undefined_table (42P01)."""
    seen: set[int] = set()
    error: BaseException | None = exc
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, "sqlstate", None) == "42P01" or getattr(error, "pgcode", None) == "42P01":
            return True
        error = getattr(error, "orig", None) or error.__cause__
    return False


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
