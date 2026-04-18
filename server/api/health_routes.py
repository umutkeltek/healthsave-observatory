"""Process and database health endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import get_session

log = logging.getLogger("healthsave")

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/api/health")
async def api_health():
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("Readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok"}
