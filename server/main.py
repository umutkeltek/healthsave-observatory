"""FastAPI app construction.

This is the ONLY file in the package that calls ``FastAPI()``. Routers are
imported from ``server.api.*`` and mounted via ``include_router``.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import health_routes, ingest, status
from .db.session import engine

log = logging.getLogger("healthsave")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(a: FastAPI):
    log.info("HealthSave server starting")
    yield
    await engine.dispose()


app = FastAPI(title="Health Data Hub", version="1.0.0", lifespan=lifespan)

app.include_router(health_routes.router)
app.include_router(ingest.router)
app.include_router(status.router)
