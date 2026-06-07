"""GET /api/apple/status - flat per-table record counts.

The iOS app parses this response with top-level metric keys (no
``{"status":"ok","counts":...}`` wrapper) and exactly the three
fields per metric: ``count``, ``oldest``, ``newest``. Do NOT change
the response shape without coordinating an iOS app release - see
CLAUDE.md.

Phase 5G observability: a per-metric SQL failure used to be invisible
to operators — the route silently substituted ``{count: 0, oldest:
None, newest: None}``, which is indistinguishable from "no data yet".
That preserves the iOS contract (the response shape stays exactly the
same), but it also masks schema drift, missing tables, and permission
errors. The Phase 5G fix is to keep the wire shape unchanged AND
bump a Prometheus counter (``STATUS_QUERY_FAILURES{metric, exception}``)
so the operator-side surface fires while the iOS-side surface
stays stable. Pair with a Grafana alert on
``rate(hdh_status_query_failures[5m]) > 0``.
"""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from .deps import get_session, verify_api_key
from .metrics import STATUS_QUERY_FAILURES

log = logging.getLogger("healthsave")

router = APIRouter()


@router.get("/api/apple/status", dependencies=[Depends(verify_api_key)])
async def apple_status(request: Request, session: AsyncSession = Depends(get_session)):
    """Return record counts so the iOS app knows what's synced."""
    # SECURITY-002: counts are owner-scoped to the resolving owner (the default
    # owner unless ALLOW_MULTI_USER is on) so the endpoint can no longer report
    # another owner's data. The wire shape (and OpenAPI description) is unchanged,
    # and a single-user install (all rows under DEFAULT_OWNER_ID) returns exactly
    # the same numbers. `request: Request` is excluded from the OpenAPI schema.
    owner_id = resolve_owner_id(request.headers.get(OWNER_HEADER))
    queries = {
        "heart_rate": "SELECT count(*), min(time), max(time) FROM heart_rate",
        "hrv": "SELECT count(*), min(time), max(time) FROM hrv",
        "blood_oxygen": "SELECT count(*), min(time), max(time) FROM blood_oxygen",
        "daily_activity": "SELECT count(*), min(date)::text, max(date)::text FROM daily_activity",
        "sleep_sessions": "SELECT count(*), min(start_time), max(start_time) FROM sleep_sessions",
        "workouts": "SELECT count(*), min(start_time), max(start_time) FROM workouts",
        "quantity_samples": "SELECT count(*), min(time), max(time) FROM quantity_samples",
    }
    params = {"owner_id": str(owner_id)}
    status = {}
    for metric, base_sql in queries.items():
        sql = f"{base_sql} WHERE owner_id = :owner_id"
        try:
            result = await session.execute(text(sql), params)
            row = result.fetchone()
            status[metric] = {
                "count": row[0] or 0,
                "oldest": str(row[1]) if row and row[1] else None,
                "newest": str(row[2]) if row and row[2] else None,
            }
        except Exception as exc:
            # iOS contract preserved: keep the silent {count:0} fallback.
            # Operator-side surface added: bump a counter labelled with
            # the exception type so Prometheus + Grafana can alert.
            log.exception("Status query failed for %s", metric)
            status[metric] = {"count": 0, "oldest": None, "newest": None}
            try:
                STATUS_QUERY_FAILURES.labels(metric=metric, exception=type(exc).__name__).inc()
            except Exception:  # pragma: no cover - metrics import optional
                log.debug("failed to record STATUS_QUERY_FAILURES{metric=%s}", metric)
    return status
