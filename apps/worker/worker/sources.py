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
from pathlib import Path
from typing import Any

log = logging.getLogger("healthsave.worker.sources")

WHOOP_DEFAULT_CRON = "*/30 * * * *"
AMAZFIT_DEFAULT_CRON = "*/30 * * * *"
POLAR_DEFAULT_CRON = "*/30 * * * *"
GOOGLE_HEALTH_DEFAULT_CRON = "*/30 * * * *"


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


def make_source_poll(
    session_factory: Any,
    *,
    spec: SourcePollSpec,
) -> Callable[[], Awaitable[None]]:
    """Return an awaitable APScheduler can invoke for one source adapter."""

    async def _run() -> None:
        import httpx
        from plugin_sdk import load_manifest
        from storage.timescale.ingest import PostgresIngestStorage

        manifest = load_manifest(_plugin_yaml(spec.slug))
        plugin_cls = _load_entrypoint(spec.entrypoint)
        plugin = plugin_cls(manifest)
        storage = PostgresIngestStorage()

        async with (
            httpx.AsyncClient(timeout=30.0) as http,
            session_factory() as session,
        ):
            try:
                result = await plugin.ingest(
                    {
                        "storage": storage,
                        "session": session,
                        "http_client": http,
                    }
                )
                await session.commit()
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
