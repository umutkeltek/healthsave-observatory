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

``metrics`` (added 2026-09-15) is what the iOS app actually decodes:
``{"metrics": {<HealthSave wire metric>: <ISO 8601 UTC, ms, "Z"> | null}}``, one key per
wire metric (``heart_rate_variability``, ``step_count``, ``activity_summaries`` ...). The flat
table keys above never matched the app's decoder (wrapper, key vocabulary and timestamp
format all differed), so the app read every answer as unreachable and the Recovery lane's
server attestation never cleared anything against this server. The flat keys stay unchanged
for any other reader; ``metrics`` is additive. Pinned in the response corpus
(``coverage.json``).
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

from contracts.ontology import all_metrics
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import readiness_repository
from storage.ports import ReadinessRepository

from ..ingestion.owner import OWNER_HEADER, resolve_owner_id
from .deps import get_session, verify_api_key
from .metrics import STATUS_QUERY_FAILURES

log = logging.getLogger("healthsave")

router = APIRouter()

# Canonical per-metric coverage (count, first/last observation) lives in the storage
# adapter; the readiness card reads the same repository.
_COVERAGE_REPO: ReadinessRepository = readiness_repository()

# max(<time column>) per metric table. Mirrors /api/apple/status so the iOS app's
# metric-to-table mapping is reused unchanged. daily_activity is date-keyed.
_LATEST_QUERIES = {
    "heart_rate": "SELECT max(time) FROM heart_rate WHERE status = 'active'",
    "hrv": "SELECT max(time) FROM hrv WHERE status = 'active'",
    "blood_oxygen": "SELECT max(time) FROM blood_oxygen WHERE status = 'active'",
    "daily_activity": "SELECT max(date)::text FROM daily_activity",
    "sleep_sessions": "SELECT max(start_time) FROM sleep_sessions WHERE status = 'active'",
    "workouts": "SELECT max(start_time) FROM workouts",
    "quantity_samples": "SELECT max(time) FROM quantity_samples",
}

# Wire families that land in a legacy table rather than as one canonical metric. Used only
# when the canonical store names no metric for the wire name.
_LEGACY_WIRE_NAMES = {
    "daily_activity": "activity_summaries",
    "sleep_sessions": "sleep_analysis",
    "workouts": "workouts",
}


def apple_wire_names() -> dict[str, list[str]]:
    """Canonical metric id -> the HealthSave wire metric name(s) it is ingested from."""
    names: dict[str, list[str]] = {}
    for metric in all_metrics():
        for mapping in metric.source_mappings:
            if mapping.source != "apple_healthkit":
                continue
            known = names.setdefault(metric.id, [])
            if mapping.source_metric not in known:
                known.append(mapping.source_metric)
    return names


def wire_timestamp(value: Any) -> str | None:
    """ISO 8601 in UTC with millisecond precision and a "Z" — the format the app sends
    and parses. A bare date (a date-keyed table) is that day's UTC midnight."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        instant = value if value.tzinfo else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        instant = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        return None
    return instant.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.get("/api/apple/coverage", dependencies=[Depends(verify_api_key)])
async def apple_coverage(request: Request, session: AsyncSession = Depends(get_session)):
    """Per-metric latest sample timestamp, for iOS backfill-recovery reconciliation."""
    owner_id = resolve_owner_id(request.headers.get(OWNER_HEADER))
    params = {"owner_id": str(owner_id)}
    coverage: dict[str, Any] = {}
    latest_raw: dict[str, Any] = {}
    for metric, base_sql in _LATEST_QUERIES.items():
        connector = "AND" if "WHERE" in base_sql else "WHERE"
        sql = f"{base_sql} {connector} owner_id = :owner_id"
        try:
            row = (await session.execute(text(sql), params)).fetchone()
            value = row[0] if row else None
            latest_raw[metric] = value
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

    # Per wire metric, in the shape the app decodes. A metric the server has no row for is
    # simply absent (the app then keeps its flag — the conservative answer).
    metrics: dict[str, str | None] = {}
    try:
        wire_names = apple_wire_names()
        rows = await _COVERAGE_REPO.fetch_canonical_coverage(session, owner_id=owner_id)
        for row in rows:
            stamp = wire_timestamp(row.get("last_observation_at"))
            for name in wire_names.get(row.get("metric_id"), []):
                current = metrics.get(name)
                if stamp and (current is None or stamp > current):
                    metrics[name] = stamp
    except Exception:
        # A failing canonical read degrades to the legacy families below, never a 500.
        log.exception("Canonical coverage read failed for /api/apple/coverage")
    for table, wire_name in _LEGACY_WIRE_NAMES.items():
        if wire_name not in metrics and latest_raw.get(table):
            metrics[wire_name] = wire_timestamp(latest_raw[table])
    coverage["metrics"] = metrics
    return coverage
