"""TimescaleDB export adapter — per-metric CSV/JSON dumps for /api/v2/export.

The read behind the data-export surface: a hard-coded whitelist of exportable
metrics maps each public metric name to a real datahub table + a fixed column
list, so the route never lets a caller name a table/column. Every query is
owner-scoped to the single-user sentinel and parameterized; date filters and the
row cap are bound params. Mirrors the legacy healthtrack export service but maps
to datahub's actual schema (e.g. workouts has no altitude_gain_m here).
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Any

from contracts._base import DEFAULT_OWNER_ID
from sqlalchemy import text

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("healthsave.storage.export")

# Default + hard cap on exported rows. Truncation past the cap is logged, never silent.
DEFAULT_ROW_LIMIT = 10_000
MAX_ROW_LIMIT = 100_000


@dataclass(frozen=True)
class MetricExportSpec:
    table: str
    time_col: str
    columns: tuple[str, ...]
    display: str
    metric_filter: str | None = None  # quantity_samples sub-metric value, bound as :metric_filter


# The ONLY source of allowed SQL identifiers. Keys are public metric names.
METRIC_EXPORTS: dict[str, MetricExportSpec] = {
    "heart_rate": MetricExportSpec(
        "heart_rate",
        "time",
        ("time", "bpm", "context", "source_id"),
        "Heart Rate",
    ),
    "hrv": MetricExportSpec(
        "hrv",
        "time",
        ("time", "value_ms", "algorithm", "context", "source_id"),
        "Heart Rate Variability",
    ),
    "blood_oxygen": MetricExportSpec(
        "blood_oxygen",
        "time",
        ("time", "spo2_pct", "context", "source_id"),
        "Blood Oxygen (SpO2)",
    ),
    "body_temperature": MetricExportSpec(
        "body_temperature",
        "time",
        ("time", "temp_celsius", "measurement_type", "source_id"),
        "Body Temperature",
    ),
    "daily_activity": MetricExportSpec(
        "daily_activity",
        "date",
        (
            "date",
            "steps",
            "distance_m",
            "floors_climbed",
            "active_calories",
            "total_calories",
            "active_minutes",
            "stand_hours",
            "avg_hr",
            "max_hr",
            "source_id",
        ),
        "Daily Activity",
    ),
    "sleep_sessions": MetricExportSpec(
        "sleep_sessions",
        "start_time",
        (
            "start_time",
            "end_time",
            "total_duration_ms",
            "awake_ms",
            "light_ms",
            "deep_ms",
            "rem_ms",
            "respiratory_rate",
            "source_id",
        ),
        "Sleep Sessions",
    ),
    "sleep_stages": MetricExportSpec(
        "sleep_stages",
        "time",
        ("time", "stage", "duration_ms"),
        "Sleep Stages",
    ),
    "workouts": MetricExportSpec(
        "workouts",
        "start_time",
        (
            "start_time",
            "end_time",
            "sport_type",
            "duration_ms",
            "avg_hr",
            "max_hr",
            "calories",
            "distance_m",
            "source_id",
        ),
        "Workouts",
    ),
    "recovery": MetricExportSpec(
        "recovery",
        "time",
        ("time", "score", "resting_hr", "hrv_ms", "spo2_pct", "skin_temp_c"),
        "Recovery",
    ),
    "stress": MetricExportSpec(
        "stress",
        "time",
        ("time", "score", "scale_type"),
        "Stress",
    ),
    "quantity_samples": MetricExportSpec(
        "quantity_samples",
        "time",
        ("time", "metric_name", "value", "unit", "source_id"),
        "Quantity Samples (All Metrics)",
    ),
    "respiratory_rate": MetricExportSpec(
        "quantity_samples",
        "time",
        ("time", "value", "unit"),
        "Respiratory Rate",
        metric_filter="respiratory_rate",
    ),
    "vo2_max": MetricExportSpec(
        "quantity_samples",
        "time",
        ("time", "value", "unit"),
        "VO2 Max",
        metric_filter="vo2_max",
    ),
    "walking_speed": MetricExportSpec(
        "quantity_samples",
        "time",
        ("time", "value", "unit"),
        "Walking Speed",
        metric_filter="walking_speed",
    ),
    "body_mass": MetricExportSpec(
        "quantity_samples",
        "time",
        ("time", "value", "unit"),
        "Body Mass",
        metric_filter="body_mass",
    ),
}

# The set returned by export_all (primary tables only, not sub-metric views).
PRIMARY_METRICS: tuple[str, ...] = (
    "heart_rate",
    "hrv",
    "blood_oxygen",
    "body_temperature",
    "daily_activity",
    "sleep_sessions",
    "sleep_stages",
    "workouts",
    "recovery",
    "stress",
    "quantity_samples",
)


def _coerce_limit(limit: int | None) -> int:
    if limit is None or limit <= 0:
        return DEFAULT_ROW_LIMIT
    if limit > MAX_ROW_LIMIT:
        log.warning("export limit %d exceeds cap %d; truncating", limit, MAX_ROW_LIMIT)
        return MAX_ROW_LIMIT
    return limit


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _fetchall(result) -> list[Any]:
    """Materialise a SQLAlchemy result into a list (test-friendly)."""
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        rows = fetchall()
        return list(rows) if rows is not None else []
    try:
        return list(result)
    except TypeError:
        return []


def _fetchone(result) -> Any | None:
    """Return the first row from a result, tolerating simple test doubles."""
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    rows = _fetchall(result)
    return rows[0] if rows else None


def _bound_start(spec: MetricExportSpec, value: date) -> date | datetime:
    if spec.time_col == "date":
        return value
    return datetime.combine(value, time.min, tzinfo=UTC)


def _bound_end(spec: MetricExportSpec, value: date) -> date | datetime:
    if spec.time_col == "date":
        return value
    return datetime.combine(value, time.max, tzinfo=UTC)


class TimescaleExportRepository:
    async def export_metric_rows(
        self,
        session: AsyncSession,
        *,
        metric: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> tuple[list[str], list[tuple]]:
        spec = METRIC_EXPORTS.get(metric)
        if spec is None:
            raise KeyError(metric)

        where_parts = ["owner_id = :owner_id"]
        params: dict[str, Any] = {"owner_id": str(owner_id)}

        if spec.metric_filter is not None:
            where_parts.append("metric_name = :metric_filter")
            params["metric_filter"] = spec.metric_filter
        if date_from is not None:
            where_parts.append(f"{spec.time_col} >= :date_from")
            params["date_from"] = _bound_start(spec, date_from)
        if date_to is not None:
            where_parts.append(f"{spec.time_col} <= :date_to")
            params["date_to"] = _bound_end(spec, date_to)

        params["limit"] = _coerce_limit(limit)
        columns = ", ".join(spec.columns)
        statement = text(
            f"""
            SELECT {columns}
            FROM {spec.table}
            WHERE {" AND ".join(where_parts)}
            ORDER BY {spec.time_col} DESC
            LIMIT :limit
            """
        )
        result = await session.execute(statement, params)
        return list(spec.columns), _fetchall(result)

    async def export_metric_json(
        self,
        session: AsyncSession,
        *,
        metric: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        columns, rows = await self.export_metric_rows(
            session,
            metric=metric,
            owner_id=owner_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return [
            {column: _serialize(value) for column, value in zip(columns, row, strict=False)}
            for row in rows
        ]

    async def export_metric_csv(
        self,
        session: AsyncSession,
        *,
        metric: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> str:
        columns, rows = await self.export_metric_rows(
            session,
            metric=metric,
            owner_id=owner_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for row in rows:
            writer.writerow("" if value is None else str(value) for value in row)
        return buffer.getvalue()

    async def list_available_metrics(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> list[dict]:
        metrics: list[dict] = []
        for metric, spec in METRIC_EXPORTS.items():
            where_parts = ["owner_id = :owner_id"]
            params: dict[str, Any] = {"owner_id": str(owner_id)}
            if spec.metric_filter is not None:
                where_parts.append("metric_name = :metric_filter")
                params["metric_filter"] = spec.metric_filter
            statement = text(
                f"""
                SELECT count(*) AS c, min({spec.time_col}) AS lo, max({spec.time_col}) AS hi
                FROM {spec.table}
                WHERE {" AND ".join(where_parts)}
                """
            )
            result = await session.execute(statement, params)
            row = _fetchone(result)
            metrics.append(
                {
                    "metric": metric,
                    "display_name": spec.display,
                    "count": 0 if row is None or row.c is None else row.c,
                    "oldest": None if row is None or row.lo is None else _serialize(row.lo),
                    "newest": None if row is None or row.hi is None else _serialize(row.hi),
                }
            )
        return metrics

    async def export_all_json(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> dict[str, list[dict]]:
        return {
            metric: await self.export_metric_json(
                session,
                metric=metric,
                owner_id=owner_id,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
            for metric in PRIMARY_METRICS
        }


default_export_repository = TimescaleExportRepository()
