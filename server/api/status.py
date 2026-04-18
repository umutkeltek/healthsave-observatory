"""GET /api/apple/status — flat per-table record counts.

The iOS app parses this response with top-level metric keys (no
``{"status":"ok","counts":...}`` wrapper). Do NOT change the response
shape without coordinating an iOS app release — see CLAUDE.md.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import get_session, verify_api_key

log = logging.getLogger("healthsave")

router = APIRouter()


@router.get("/api/apple/status", dependencies=[Depends(verify_api_key)])
async def apple_status(session: AsyncSession = Depends(get_session)):
    """Return record counts so the iOS app knows what's synced."""
    queries = {
        "heart_rate": "SELECT count(*), min(time), max(time) FROM heart_rate",
        "hrv": "SELECT count(*), min(time), max(time) FROM hrv",
        "blood_oxygen": "SELECT count(*), min(time), max(time) FROM blood_oxygen",
        "daily_activity": "SELECT count(*), min(date)::text, max(date)::text FROM daily_activity",
        "sleep_sessions": "SELECT count(*), min(start_time), max(start_time) FROM sleep_sessions",
        "workouts": "SELECT count(*), min(start_time), max(start_time) FROM workouts",
        "quantity_samples": "SELECT count(*), min(time), max(time) FROM quantity_samples",
    }
    status = {}
    for metric, sql in queries.items():
        try:
            result = await session.execute(text(sql))
            row = result.fetchone()
            status[metric] = {
                "count": row[0] or 0,
                "oldest": str(row[1]) if row and row[1] else None,
                "newest": str(row[2]) if row and row[2] else None,
            }
        except Exception as exc:
            log.warning("Status query failed for %s: %s", metric, exc)
            status[metric] = {"count": 0, "oldest": None, "newest": None}
    return status
