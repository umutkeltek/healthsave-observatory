"""FastAPI app construction.

This is the ONLY file in the package that calls ``FastAPI()``. Routers are
imported from ``server.api.*`` and mounted via ``include_router``.

Analysis lifespan wiring (post-Phase 4 split):
  * Load ``config.yaml`` (defaults when missing) into ``AnalysisConfig``.
  * Construct ``HealthLLMClient`` + ``AnalysisEngine`` for the inline
    ``/api/insights/trigger`` route.
  * Stash both on ``app.state`` so routes can reach them.
  * The ``AnalysisScheduler`` runs in ``apps/worker`` — NOT here.
    API uptime is no longer coupled to scheduler bugs/memory.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from analysis.config import load_config
from analysis.engine import AnalysisEngine
from analysis.llm.client import HealthLLMClient
from fastapi import FastAPI

from .api import health_routes, ingest, insights, metrics, status
from .db.session import async_session, engine
from .ingestion.registry import resolve_from_env

log = logging.getLogger("healthsave")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(a: FastAPI):
    log.info("HealthSave server starting")
    config_path = Path(os.getenv("ANALYSIS_CONFIG", "/app/config.yaml"))
    analysis_config = load_config(config_path)
    llm_client = HealthLLMClient(analysis_config.llm)
    analysis_engine = AnalysisEngine(async_session, llm_client, analysis_config)
    a.state.analysis_config = analysis_config
    a.state.analysis_engine = analysis_engine
    # Phase 4D: trigger handler writes pipeline_runs records via this
    # factory. Tests that don't set it get a no-op (graceful degrade).
    a.state.session_factory = async_session
    storage, audit_log = resolve_from_env()
    a.state.storage = storage
    a.state.audit_log = audit_log
    log.info("storage backend resolved: %s", type(storage).__name__)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Health Data Hub", version="1.0.0", lifespan=lifespan)

app.include_router(health_routes.router)
app.include_router(ingest.router)
app.include_router(metrics.router)
app.include_router(status.router)
app.include_router(insights.router)
