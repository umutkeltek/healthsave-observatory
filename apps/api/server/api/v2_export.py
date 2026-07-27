"""GET /api/v2/export — per-metric CSV/JSON data export (additive v2 read).

Ports the legacy healthtrack export surface: list exportable metrics with counts
and date ranges, dump one metric as CSV or JSON, or export-all as a single JSON
object. The whitelist + SQL live in the storage adapter; this route only parses
query params, resolves the day shortcut, and shapes the HTTP response. Owner-
scoped to the single-user sentinel like the rest of the v2 read plane.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from contracts._base import DEFAULT_OWNER_ID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from storage.defaults import export_repository
from storage.ports import ExportRepository

from .deps import get_session, verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])
_EXPORT_REPO: ExportRepository = export_repository()
log = logging.getLogger("healthsave.api.v2_export")

# SECURITY-004 / PERF-02: hard ceiling on rows returned by a single export.
# Enforced at runtime (not via Query(le=...)) so the v2 OpenAPI snapshot stays
# byte-identical and no lock regeneration is needed.
_MAX_EXPORT_LIMIT = 100_000


@router.get("/export/metrics")
async def list_export_metrics(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    return await _EXPORT_REPO.list_available_metrics(session, owner_id=DEFAULT_OWNER_ID)


@router.get("/export")
async def export_data(
    metric: str = Query(...),
    format: str = Query("json"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    days: int | None = Query(None),
    limit: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    # Normalize the FastAPI Query() defaults to real values so the handler
    # behaves identically whether FastAPI resolved the query string or the
    # function was invoked directly (e.g. in unit tests). Without this, an
    # unset optional carries the Query sentinel object, not None, and the
    # days-shortcut below would never fire.
    date_from = date_from if isinstance(date_from, date) else None
    date_to = date_to if isinstance(date_to, date) else None
    days = days if isinstance(days, int) else None
    limit = limit if isinstance(limit, int) else None

    # SECURITY-004 / PERF-02: never allow an unbounded export. None or a
    # non-positive limit defaults to the cap; larger values are clamped down.
    limit = _MAX_EXPORT_LIMIT if limit is None or limit <= 0 else min(limit, _MAX_EXPORT_LIMIT)

    if days and date_from is None:
        date_from = (datetime.now(UTC) - timedelta(days=days)).date()
    if days and date_to is None:
        date_to = datetime.now(UTC).date()

    if format == "csv":
        if metric == "all":
            raise HTTPException(
                422,
                "CSV format does not support metric=all; export one metric at a time.",
            )
        try:
            csv_data = await _EXPORT_REPO.export_metric_csv(
                session,
                metric=metric,
                owner_id=DEFAULT_OWNER_ID,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown metric: {metric}") from exc
        return StreamingResponse(
            iter([csv_data]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=healthsave_{metric}.csv"},
        )

    if metric == "all":
        return await _EXPORT_REPO.export_all_json(
            session,
            owner_id=DEFAULT_OWNER_ID,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    try:
        return await _EXPORT_REPO.export_metric_json(
            session,
            metric=metric,
            owner_id=DEFAULT_OWNER_ID,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except KeyError as exc:
        raise HTTPException(404, f"unknown metric: {metric}") from exc
