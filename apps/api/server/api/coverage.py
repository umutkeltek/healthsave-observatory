"""GET /api/apple/coverage - per-metric latest-sample timestamp, owner-scoped.

Lean companion to ``/api/apple/status``: returns only the newest sample time
per metric as ``{metric: iso_ts_or_null}``. The HealthSave iOS app uses this
for backfill-recovery reconciliation -- it clears a sticky ``deliveryIncomplete``
flag only when this proves the server holds data at/after the flagged gap
window. That is a server-attested recovery path (parallel to the full-reread
``recovered`` path in ``SyncStateStore``) and it preserves the no-silent-loss
invariant: if the server lacks the data the value is ``None`` (or behind the
window) and the flag stays, so a genuine gap still surfaces the Backfill
signal. See ``ios_app/BACKFILL_RECOVERY_RECONCILIATION.md``.

SECURITY-002: like ``/api/apple/status``, results are owner-scoped via
``resolve_owner_id`` so the endpoint cannot report another owner's latest
sample. A single-user install (all rows under the default owner) returns
identical values. ``request: Request`` is excluded from the OpenAPI schema.

Metric keys mirror ``/api/apple/status`` so the iOS app reuses its existing
metric-to-table mapping. ``quantity_samples`` is the catch-all table; its value
is the newest across all quantity samples (sufficient to prove the server is
receiving data for that class).
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

# max(<time column>) per metric table. Mirrors /api/apple/status so the iOS app's
# metric-to-table mapping is reused unchanged. daily_activity is date-keyed.
_LATEST_QUERIES = {
    "heart_rate": "SELECT max(time) FROM heart_rate",
    "hrv": "SELECT max(time) FROM hrv",
    "blood_oxygen": "SELECT max(time) FROM blood_oxygen",
    "daily_activity": "SELECT max(date)::text FROM daily_activity",
    "sleep_sessions": "SELECT max(start_time) FROM sleep_sessions",
    "workouts": "SELECT max(start_time) FROM workouts",
    "quantity_samples": "SELECT max(time) FROM quantity_samples",
}


@router.get("/api/apple/coverage", dependencies=[Depends(verify_api_key)])
async def apple_coverage(request: Request, session: AsyncSession = Depends(get_session)):
    """Per-metric latest sample timestamp, for iOS backfill-recovery reconciliation."""
    owner_id = resolve_owner_id(request.headers.get(OWNER_HEADER))
    params = {"owner_id": str(owner_id)}
    coverage: dict[str, str | None] = {}
    for metric, base_sql in _LATEST_QUERIES.items():
        sql = f"{base_sql} WHERE owner_id = :owner_id"
        try:
            row = (await session.execute(text(sql), params)).fetchone()
            value = row[0] if row else None
            coverage[metric] = str(value) if value else None
        except Exception as exc:
            # Same operator-surface discipline as /api/apple/status: never let a
            # per-metric SQL failure 500 the whole response. The iOS
            # reconciliation treats None conservatively (does NOT clear the
            # flag), so degrading a failing metric to None is safe.
            log.exception("Coverage query failed for %s", metric)
            coverage[metric] = None
            try:
                STATUS_QUERY_FAILURES.labels(metric=metric, exception=type(exc).__name__).inc()
            except Exception:  # pragma: no cover - metrics import optional
                log.debug("failed to record STATUS_QUERY_FAILURES{metric=%s}", metric)
    return coverage
