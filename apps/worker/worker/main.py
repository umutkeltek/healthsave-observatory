"""Worker entrypoint.

Loads the same ``AnalysisConfig`` + ``AnalysisEngine`` the API uses,
constructs an ``AnalysisScheduler``, and runs it until SIGTERM. The
API process no longer starts a scheduler — this is the only home of
scheduled work in the v2 layout.

Run via ``python -m worker.main``. The Compose service runs the
project's standard image with this command.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from pathlib import Path

from analysis.config import load_config
from analysis.engine import AnalysisEngine
from analysis.llm.client import HealthLLMClient
from analysis.scheduler import AnalysisScheduler
from server.db.session import async_session, engine

from .listener import listener_event_mask, make_listener
from .sources import register_whoop_poll

log = logging.getLogger("healthsave.worker")


async def run() -> None:
    """Construct + start the scheduler; wait for SIGINT/SIGTERM; shut down cleanly."""
    config_path = Path(os.getenv("ANALYSIS_CONFIG", "/app/config.yaml"))
    analysis_config = load_config(config_path)
    llm_client = HealthLLMClient(analysis_config.llm)
    analysis_engine = AnalysisEngine(async_session, llm_client, analysis_config)
    scheduler = AnalysisScheduler(analysis_engine, analysis_config)

    log.info("worker starting; scheduler enabled")
    scheduler.start()

    # Wire pipeline_runs ledger writes (Phase 4B). The listener fires
    # on EVENT_JOB_{SUBMITTED,EXECUTED,ERROR,MISSED} and writes one
    # row per scheduled instant. No-op when the scheduler didn't start
    # (all jobs disabled) — `scheduler.scheduler` is None in that case.
    if scheduler.scheduler is not None:
        leased_by = f"{socket.gethostname()}:{os.getpid()}"
        scheduler.scheduler.add_listener(
            make_listener(async_session, leased_by=leased_by),
            listener_event_mask(),
        )
        log.info("pipeline_runs ledger listener attached (leased_by=%s)", leased_by)

    # Source-plugin polls (Phase 7-pre). Env-gated: set WHOOP_POLL_CRON
    # to a crontab expression to enable the Whoop poll on this worker.
    # If analysis jobs are all disabled, scheduler.scheduler is None —
    # spin up a standalone AsyncIOScheduler so the source polls still
    # run. Stored on the AnalysisScheduler wrapper so shutdown reaches it.
    source_scheduler = None
    whoop_cron = os.environ.get("WHOOP_POLL_CRON")
    if whoop_cron:
        if scheduler.scheduler is not None:
            register_whoop_poll(scheduler.scheduler, async_session, cron=whoop_cron)
        else:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            source_scheduler = AsyncIOScheduler()
            register_whoop_poll(source_scheduler, async_session, cron=whoop_cron)
            source_scheduler.start()
            log.info("source-only AsyncIOScheduler started (analysis jobs all disabled)")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("worker stopping")
        scheduler.shutdown()
        if source_scheduler is not None:
            source_scheduler.shutdown(wait=False)
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
