"""Source-plugin poll registration for the worker scheduler.

Source plugins (Whoop, Amazfit next, future) are poll-based: the
worker invokes their ``ingest()`` on a cron schedule. This module
exposes:

  * :func:`make_whoop_poll` — builds the awaitable APScheduler invokes
    each tick. Opens a session, instantiates an httpx client + an
    IngestStorage, runs ``WhoopSource.ingest``, commits or rolls back.
    Failures are logged + re-raised so the existing pipeline_runs
    listener marks the run as failed.
  * :func:`register_whoop_poll` — adds the job to a given APScheduler
    with ``max_instances=1`` + ``coalesce=True`` (Whoop polls overlap
    safely thanks to dedup unique indexes, but we still avoid
    backed-up duplicates).

The wiring in :mod:`worker.main` is intentionally env-gated
(``WHOOP_POLL_CRON``) rather than config.yaml-gated for v1 — the
analysis config schema does not yet have a sources section. A future
slice can lift this into the config layer once the source surface
stabilises.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("healthsave.worker.sources")

# Default cron — every 30 minutes. Whoop's rate limit is 100 req/min
# and a 30-minute cadence is plenty for a single-user poll. Override
# via the WHOOP_POLL_CRON env var.
WHOOP_DEFAULT_CRON = "*/30 * * * *"

# Amazfit / Zepp: same cadence as Whoop. Zepp does not publish a rate
# limit; the legacy personal_stack scheduler ran hourly and we tighten
# slightly for fresher data. Override via the AMAZFIT_POLL_CRON env var.
AMAZFIT_DEFAULT_CRON = "*/30 * * * *"


def _whoop_plugin_yaml() -> Path:
    """Locate the Whoop plugin manifest. The Docker image copies
    ``plugins/sources/whoop/plugin.yaml`` to ``/app/plugins/...``;
    repo-root checkouts find it at ``<repo>/plugins/sources/...``.
    """
    here = Path(__file__).resolve()
    # apps/worker/worker/sources.py -> repo root
    repo_root = here.parents[3]
    return repo_root / "plugins" / "sources" / "whoop" / "plugin.yaml"


def make_whoop_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    """Return an awaitable APScheduler can invoke on every tick.

    ``session_factory`` is an ``async_sessionmaker``-shaped callable —
    each call returns a fresh ``AsyncSession`` that the wrapper opens
    inside an ``async with`` for transaction discipline.
    """

    async def _run() -> None:
        import httpx
        from plugin_sdk import load_manifest
        from server.ingestion.storage import PostgresIngestStorage

        from plugins.sources.whoop import WhoopSource

        manifest = load_manifest(_whoop_plugin_yaml())
        plugin = WhoopSource(manifest)
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
                log.info("whoop poll: %s", result)
            except Exception:
                await session.rollback()
                log.exception("whoop poll failed")
                raise

    return _run


def register_whoop_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = WHOOP_DEFAULT_CRON,
    job_id: str = "whoop_poll",
) -> str:
    """Register the Whoop poll on ``scheduler``. Returns the job id.

    APScheduler import is deferred so module import stays cheap for
    pytest collection without a running event loop.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        make_whoop_poll(session_factory),
        CronTrigger.from_crontab(cron),
        id=job_id,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("registered %s cron=%s", job_id, cron)
    return job_id


def _amazfit_plugin_yaml() -> Path:
    """Locate the Amazfit plugin manifest. Same layout as Whoop."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    return repo_root / "plugins" / "sources" / "amazfit" / "plugin.yaml"


def make_amazfit_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    """Return an awaitable APScheduler can invoke on every tick.

    Lifecycle matches make_whoop_poll: open httpx + session, instantiate
    plugin, run ingest, commit/rollback. AmazfitSource.ingest fails loud
    on expired token (no refresh primitive), so the worker's
    pipeline_runs ledger picks up the failure.
    """

    async def _run() -> None:
        import httpx
        from plugin_sdk import load_manifest
        from server.ingestion.storage import PostgresIngestStorage

        from plugins.sources.amazfit import AmazfitSource

        manifest = load_manifest(_amazfit_plugin_yaml())
        plugin = AmazfitSource(manifest)
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
                log.info("amazfit poll: %s", result)
            except Exception:
                await session.rollback()
                log.exception("amazfit poll failed")
                raise

    return _run


def register_amazfit_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = AMAZFIT_DEFAULT_CRON,
    job_id: str = "amazfit_poll",
) -> str:
    """Register the Amazfit poll on ``scheduler``. Returns the job id."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        make_amazfit_poll(session_factory),
        CronTrigger.from_crontab(cron),
        id=job_id,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("registered %s cron=%s", job_id, cron)
    return job_id
