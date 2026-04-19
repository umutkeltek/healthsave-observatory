"""FastAPI app construction.

This is the ONLY file in the package that calls ``FastAPI()``. Routers are
imported from ``server.api.*`` and mounted via ``include_router``.

Analysis lifespan wiring:
  * Load ``config.yaml`` (defaults when missing) into ``AnalysisConfig``.
  * Construct ``HealthLLMClient`` + ``AnalysisEngine`` + ``AnalysisScheduler``.
  * Stash all three on ``app.state`` so routes and diagnostics can reach them.
  * Start the scheduler after app state is populated; shut it down before
    disposing the DB engine on exit.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from analysis.config import load_config
from analysis.engine import AnalysisEngine
from analysis.llm.client import HealthLLMClient
from analysis.scheduler import AnalysisScheduler

from .api import health_routes, ingest, insights, status
from .db.session import async_session, engine

log = logging.getLogger("healthsave")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(a: FastAPI):
    log.info("HealthSave server starting")
    config_path = Path(os.getenv("ANALYSIS_CONFIG", "/app/config.yaml"))
    analysis_config = load_config(config_path)
    llm_client = HealthLLMClient(analysis_config.llm)
    analysis_engine = AnalysisEngine(async_session, llm_client, analysis_config)
    scheduler = AnalysisScheduler(analysis_engine, analysis_config)
    a.state.analysis_config = analysis_config
    a.state.analysis_engine = analysis_engine
    a.state.scheduler = scheduler
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        await engine.dispose()


app = FastAPI(title="Health Data Hub", version="1.0.0", lifespan=lifespan)

app.include_router(health_routes.router)
app.include_router(ingest.router)
app.include_router(status.router)
app.include_router(insights.router)
