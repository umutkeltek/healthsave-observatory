"""Source-plugin poll registration for the worker scheduler.

Each source adapter still exposes a small named wrapper, but the runtime poll
lifecycle is owned by :func:`make_source_poll`: locate manifest, instantiate
plugin, open HTTP/session resources, call ``ingest()``, commit or rollback.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from storage.timescale.fusion import default_repository as default_fusion_repository

from contracts import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, PluginManifest

log = logging.getLogger("healthsave.worker.sources")

WHOOP_DEFAULT_CRON = "*/30 * * * *"
AMAZFIT_DEFAULT_CRON = "*/30 * * * *"
POLAR_DEFAULT_CRON = "*/30 * * * *"
GOOGLE_HEALTH_DEFAULT_CRON = "*/30 * * * *"

# After an outage longer than a plugin's own lookback, the next poll reaches
# back to the last successful poll, but never further than this: one poll
# must not ask a vendor for unbounded history.
MAX_BACKFILL = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class SourcePollSpec:
    """Adapter-specific inputs for the shared source poll lifecycle."""

    slug: str
    entrypoint: str
    log_label: str


WHOOP_SPEC = SourcePollSpec(
    slug="whoop",
    entrypoint="plugins.sources.whoop:WhoopSource",
    log_label="whoop",
)
AMAZFIT_SPEC = SourcePollSpec(
    slug="amazfit",
    entrypoint="plugins.sources.amazfit:AmazfitSource",
    log_label="amazfit",
)
POLAR_SPEC = SourcePollSpec(
    slug="polar",
    entrypoint="plugins.sources.polar:PolarSource",
    log_label="polar",
)
GOOGLE_HEALTH_SPEC = SourcePollSpec(
    slug="google_health",
    entrypoint="plugins.sources.google_health:GoogleHealthSource",
    log_label="google health",
)


def _plugin_yaml(slug: str) -> Path:
    """Locate a source plugin manifest without hard-coding repo depth."""
    from plugin_sdk import find_plugin_manifest

    return find_plugin_manifest(slug, kind="source", start=Path(__file__))


def _load_entrypoint(entrypoint: str):
    module_name, sep, attr = entrypoint.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"invalid source plugin entrypoint: {entrypoint!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _plugin_lookback(entrypoint: str) -> timedelta | None:
    """The window a plugin fetches when given no ``since`` (its DEFAULT_LOOKBACK)."""
    module = importlib.import_module(entrypoint.partition(":")[0])
    lookback = getattr(module, "DEFAULT_LOOKBACK", None)
    return lookback if isinstance(lookback, timedelta) else None


def backfill_since(
    last_success: datetime | None,
    *,
    lookback: timedelta | None,
    now: datetime,
) -> datetime | None:
    """The fetch start that covers the gap since ``last_success``.

    None keeps the plugin's default window: no poll has succeeded yet, or the
    default window already reaches back past the last success. Otherwise
    reach back one lookback before the last success (vendors score records
    late, which a healthy run of polls would have re-fetched), bounded by
    :data:`MAX_BACKFILL`.
    """
    if last_success is None or lookback is None or last_success >= now - lookback:
        return None
    return max(last_success - lookback, now - MAX_BACKFILL)


def _has_session_capability(manifest: PluginManifest) -> bool:
    return any(
        capability.record_shape == "session"
        and capability.aggregation_scope == "interval_component"
        for capability in manifest.source_capabilities
    )


async def reconcile_source_poll_sessions(
    session: Any,
    *,
    manifest: PluginManifest,
    fusion_repository: Any = default_fusion_repository,
    owner_id=DEFAULT_OWNER_ID,
    workspace_id=DEFAULT_WORKSPACE_ID,
) -> int:
    """Run reversible session fusion after a source poll.

    This consumes manifest semantics and confirmed device links; it does not
    create identity links or mutate raw observations.
    """

    if not _has_session_capability(manifest):
        return 0

    pairs = await fusion_repository.find_session_candidate_pairs(
        session,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    for pair in pairs:
        await fusion_repository.reconcile_session_pair(
            session,
            owner_id=owner_id,
            workspace_id=workspace_id,
            provider_subject_id=pair.provider_subject_id,
            direct=pair.direct,
            relayed=pair.relayed,
            device_link=pair.device_link,
            decided_by=f"source-poll:{manifest.id}",
        )
    return len(pairs)


def make_source_poll(
    session_factory: Any,
    *,
    spec: SourcePollSpec,
    fusion_repository: Any = default_fusion_repository,
) -> Callable[[], Awaitable[None]]:
    """Return an awaitable APScheduler can invoke for one source adapter."""

    async def _run() -> None:
        import httpx
        from plugin_sdk import load_manifest
        from storage.timescale import source_poll_cursors
        from storage.timescale.ingest import PostgresIngestStorage

        manifest = load_manifest(_plugin_yaml(spec.slug))
        plugin_cls = _load_entrypoint(spec.entrypoint)
        plugin = plugin_cls(manifest)
        storage = PostgresIngestStorage()
        polled_at = datetime.now(UTC)

        async with (
            httpx.AsyncClient(timeout=30.0) as http,
            session_factory() as session,
        ):
            try:
                payload: dict[str, Any] = {
                    "storage": storage,
                    "session": session,
                    "http_client": http,
                }
                last_success = await source_poll_cursors.get_last_successful_poll(
                    session, provider=spec.slug, owner_id=DEFAULT_OWNER_ID
                )
                since = backfill_since(
                    last_success, lookback=_plugin_lookback(spec.entrypoint), now=polled_at
                )
                if since is not None:
                    payload["since"] = since
                    log.info(
                        "%s poll: last success %s, backfilling from %s",
                        spec.log_label,
                        last_success.isoformat(),
                        since.isoformat(),
                    )
                result = await plugin.ingest(payload)
                # Same transaction as the poll's data: the cursor never claims
                # a poll whose writes rolled back.
                await source_poll_cursors.record_successful_poll(
                    session, provider=spec.slug, owner_id=DEFAULT_OWNER_ID, polled_at=polled_at
                )
                await session.commit()
                try:
                    reconciled = await reconcile_source_poll_sessions(
                        session,
                        manifest=manifest,
                        fusion_repository=fusion_repository,
                    )
                    if reconciled:
                        await session.commit()
                        log.info(
                            "%s fusion reconciliation: %d candidate pair(s)",
                            spec.log_label,
                            reconciled,
                        )
                except Exception:
                    await session.rollback()
                    log.exception("%s fusion reconciliation failed", spec.log_label)
                log.info("%s poll: %s", spec.log_label, result)
            except Exception:
                await session.rollback()
                log.exception("%s poll failed", spec.log_label)
                raise

    return _run


def _register_source_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    spec: SourcePollSpec,
    cron: str,
    job_id: str,
) -> str:
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        make_source_poll(session_factory, spec=spec),
        CronTrigger.from_crontab(cron),
        id=job_id,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("registered %s cron=%s", job_id, cron)
    return job_id


def make_whoop_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=WHOOP_SPEC)


def register_whoop_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = WHOOP_DEFAULT_CRON,
    job_id: str = "whoop_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=WHOOP_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_amazfit_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=AMAZFIT_SPEC)


def register_amazfit_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = AMAZFIT_DEFAULT_CRON,
    job_id: str = "amazfit_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=AMAZFIT_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_polar_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=POLAR_SPEC)


def register_polar_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = POLAR_DEFAULT_CRON,
    job_id: str = "polar_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=POLAR_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_google_health_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=GOOGLE_HEALTH_SPEC)


def register_google_health_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = GOOGLE_HEALTH_DEFAULT_CRON,
    job_id: str = "google_health_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=GOOGLE_HEALTH_SPEC,
        cron=cron,
        job_id=job_id,
    )
