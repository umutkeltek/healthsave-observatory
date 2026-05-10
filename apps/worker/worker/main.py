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

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("worker stopping")
        scheduler.shutdown()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
