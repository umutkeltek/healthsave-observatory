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

Phase 5G defense-in-depth: ``_assert_lifespan_state`` runs once after
the app.state attributes are populated and raises ``RuntimeError`` if
any required attribute is missing. This catches a future regression in
``lifespan()`` (e.g. someone removes the ``a.state.session_factory =
async_session`` line) at boot time — instead of silently falling
through to insights.py's degraded-mode counter at first request. The
counter is the runtime warning; this assertion is the build-time safety
net.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from analysis.config import load_config
from analysis.engine import AnalysisEngine
from analysis.llm.client import HealthLLMClient
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import (
    health_routes,
    ingest,
    insights,
    metrics,
    status,
    sync,
    v2_agents,
    v2_changes,
    v2_experiments,
    v2_export,
    v2_identity,
    v2_insights,
    v2_intelligence,
    v2_meta,
    v2_metrics,
    v2_privacy,
    v2_readiness,
    v2_receipts,
    v2_sources,
)
from .api.deps import warn_if_auth_disabled
from .api.ingest import _load_apple_health_plugin
from .db.session import async_session, engine
from .ingestion.registry import resolve_from_env

log = logging.getLogger("healthsave")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

_REQUIRED_STATE_ATTRS: tuple[str, ...] = (
    "analysis_config",
    "analysis_engine",
    "session_factory",
    "storage",
    "audit_log",
    "measurement_projection",
    "apple_health_plugin",
)


def _assert_lifespan_state(a: FastAPI) -> None:
    """Fail loudly at startup if a required app.state attribute is missing.

    Phase 5G fix for audit MAJOR M6: pre-5G a regression in lifespan()
    that forgot to set ``session_factory`` would only surface at first
    request, where insights._record_trigger_run silently degraded to
    'just await coro' with no log line. The audit caught the silent
    path. This assertion catches the cause at boot.
    """
    missing = [name for name in _REQUIRED_STATE_ATTRS if not hasattr(a.state, name)]
    if missing:
        raise RuntimeError(
            f"FastAPI lifespan did not populate required app.state attributes: "
            f"{missing}. This is a regression in apps/api/server/main.py::lifespan."
        )


@asynccontextmanager
async def lifespan(a: FastAPI):
    log.info("HealthSave server starting")
    warn_if_auth_disabled()
    config_path = Path(os.getenv("ANALYSIS_CONFIG", "/app/config.yaml"))
    analysis_config = load_config(config_path)
    llm_client = HealthLLMClient(analysis_config.llm)
    analysis_engine = AnalysisEngine(async_session, llm_client, analysis_config)
    a.state.analysis_config = analysis_config
    a.state.analysis_engine = analysis_engine
    # Phase 4D: trigger handler writes pipeline_runs records via this
    # factory. A missing attribute is a Phase 5G regression — caught
    # by _assert_lifespan_state below; insights.py also bumps a
    # PIPELINE_RUNS_LEDGER_FAILURES{phase=session_factory_missing}
    # counter at request time as a runtime safety net.
    a.state.session_factory = async_session
    storage, audit_log = resolve_from_env()
    a.state.storage = storage
    a.state.audit_log = audit_log
    if type(storage).__name__ == "PostgresIngestStorage":
        from storage.timescale.measurements import default_projection_repository

        a.state.measurement_projection = default_projection_repository
    else:
        a.state.measurement_projection = None
    log.info("storage backend resolved: %s", type(storage).__name__)
    # Phase 6.1: prime the Apple Health plugin at startup so a broken
    # plugins/ layout fails LOUD at boot rather than degrading the
    # first user request to a 500. The route's _resolve_apple_health_plugin
    # reads off app.state first; an explicit attribute beats falling
    # through to the lazy module-level cache, and the assertion below
    # catches any future regression that drops this line.
    a.state.apple_health_plugin = _load_apple_health_plugin()
    log.info(
        "Apple Health plugin primed at lifespan: %s",
        type(a.state.apple_health_plugin).__name__,
    )
    _assert_lifespan_state(a)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Health Data Hub", version="1.0.0", lifespan=lifespan)


@app.exception_handler(json.JSONDecodeError)
async def handle_invalid_json(_: Request, exc: json.JSONDecodeError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "invalid JSON body"})


# SECURITY-004: reject oversized request bodies. This is a coarse in-app guard
# (Content-Length based); the durable limit belongs at the reverse proxy /
# gateway (e.g. nginx client_max_body_size). Keep both.
MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(16 * 1024 * 1024)))


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid Content-Length"})
        if declared > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})
    return await call_next(request)


app.include_router(health_routes.router)
app.include_router(ingest.router)
app.include_router(metrics.router)
app.include_router(status.router)
app.include_router(sync.router)
app.include_router(insights.router)
app.include_router(v2_agents.router)
app.include_router(v2_changes.router)
app.include_router(v2_experiments.router)
app.include_router(v2_export.router)
app.include_router(v2_identity.router)
app.include_router(v2_insights.router)
app.include_router(v2_intelligence.router)
app.include_router(v2_meta.router)
app.include_router(v2_metrics.router)
app.include_router(v2_privacy.router)
app.include_router(v2_readiness.router)
app.include_router(v2_receipts.router)
app.include_router(v2_sources.router)
