"""TimescaleDB-backed analysis SQL.

Phase 5F lifted every ``import sqlalchemy`` line out of
``packages/py/analysis/engine.py``,
``packages/py/analysis/statistical/aggregator.py``,
``packages/py/analysis/statistical/anomaly.py``, and
``packages/py/analysis/statistical/trends.py`` into this module. The
analysis classes (``AnalysisEngine``, ``DataAggregator``,
``AnomalyDetector``, ``TrendAnalyzer``) keep their orchestration and
business logic in the ``analysis`` package; they now import these
functions to talk to TimescaleDB. After 5F the storage zone invariant
(``tests/contract/test_storage_invariant.py``) is enforced — only
files inside ``packages/py/storage/`` may ``import sqlalchemy``.

Functions in this module take a SQLAlchemy ``AsyncSession`` (or any
duck-typed equivalent — the test suite passes ``AsyncMock`` instances)
and return Python primitives or row-lists. They never raise from a
missing-table or empty-result; the analysis layer is responsible for
"nothing detected" semantics.

Cycle note: this module imports nothing from ``analysis.*`` or
``server.*``. Earlier phases (5C, 5E) needed lazy imports because
``storage.timescale.measurements`` reaches into ``server.ingestion``
helpers; the analysis SQL surface has no such cross-package coupling,
so eager imports are safe here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from sqlalchemy import text

if TYPE_CHECKING:
    from uuid import UUID

# ──────────────────────────────────────────────────────────────────
#  Shared helpers
# ──────────────────────────────────────────────────────────────────


def _fetchall(result) -> list[Any]:
    """Materialise a SQLAlchemy result into a list (test-friendly).

    Real ``sqlalchemy.engine.Result`` exposes ``.fetchall()``. Some
    test fakes only support iteration — fall back to ``list(result)``.
    """
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        rows = fetchall()
        return list(rows) if rows is not None else []
    try:
        return list(result)
    except TypeError:
        return []


# ──────────────────────────────────────────────────────────────────
#  analysis_runs lifecycle  (was: analysis.engine internals)
# ──────────────────────────────────────────────────────────────────


async def begin_run(session, run_type: str) -> int | None:
    """Insert ``analysis_runs`` row with ``status='running'`` and return its id."""
    result = await session.execute(
        text(
            """
            INSERT INTO analysis_runs (run_type, status, started_at)
            VALUES (:run_type, 'running', :now)
            RETURNING id
            """
        ),
        {"run_type": run_type, "now": datetime.now(tz=UTC)},
    )
    row = result.fetchone()
    return row.id if row is not None else None


async def mark_run_skipped(session, run_id: int | None) -> None:
    await session.execute(
        text(
            """
            UPDATE analysis_runs
               SET status = 'skipped',
                   completed_at = :now
             WHERE id = :id
            """
        ),
        {"now": datetime.now(tz=UTC), "id": run_id},
    )


async def mark_run_completed(
    session,
    run_id: int | None,
    *,
    llm_provider: str | None = None,
    llm_tokens_in: int | None = None,
    llm_tokens_out: int | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE analysis_runs
               SET status = 'completed',
                   completed_at = :now,
                   llm_provider = :provider,
                   llm_tokens_in = :tokens_in,
                   llm_tokens_out = :tokens_out
             WHERE id = :id
            """
        ),
        {
            "now": datetime.now(tz=UTC),
            "provider": llm_provider,
            "tokens_in": llm_tokens_in,
            "tokens_out": llm_tokens_out,
            "id": run_id,
        },
    )


async def mark_run_failed(session, run_id: int, error_message: str) -> None:
    """Best-effort ``status='failed'`` UPDATE.

    Caller is responsible for swallowing secondary errors so the
    ORIGINAL exception propagates; this function commits its own
    transaction so the failed-row write is durable even when the
    enclosing transaction rolls back.
    """
    await session.execute(
        text(
            """
            UPDATE analysis_runs
               SET status = 'failed',
                   completed_at = :now,
                   error_message = :error
             WHERE id = :id
            """
        ),
        {"now": datetime.now(tz=UTC), "error": error_message, "id": run_id},
    )
    await session.commit()


async def insert_finding(
    session,
    *,
    run_id: int | None,
    finding_type: str,
    metric: str | None,
    severity: str,
    structured_data: dict[str, Any],
) -> int | None:
    """Persist one finding row and return its id."""
    result = await session.execute(
        text(
            """
            INSERT INTO analysis_findings
                (run_id, finding_type, metric, severity, structured_data)
            VALUES (:run_id, :finding_type, :metric, :severity, :structured_data)
            RETURNING id
            """
        ),
        {
            "run_id": run_id,
            "finding_type": finding_type,
            "metric": metric,
            "severity": severity,
            "structured_data": json.dumps(structured_data, default=str),
        },
    )
    row = result.fetchone()
    return row.id if row is not None else None


async def insert_insight(
    session,
    *,
    run_id: int | None,
    insight_type: str,
    narrative: str,
    findings_used: list[int],
) -> None:
    """Persist a narrative insight produced by the LLM narrator."""
    await session.execute(
        text(
            """
            INSERT INTO analysis_insights
                (run_id, insight_type, narrative, findings_used)
            VALUES (:run_id, :insight_type, :narrative, :findings_used)
            """
        ),
        {
            "run_id": run_id,
            "insight_type": insight_type,
            "narrative": narrative,
            "findings_used": findings_used,
        },
    )


async def within_cooldown(session, run_type: str, cooldown_minutes: int) -> bool:
    """True when a recent ``analysis_runs`` row makes another ad-hoc run redundant."""
    if cooldown_minutes <= 0:
        return False
    since = datetime.now(tz=UTC) - timedelta(minutes=cooldown_minutes)
    result = await session.execute(
        text(
            """
            SELECT id
            FROM analysis_runs
            WHERE run_type = :run_type
              AND started_at >= :since
              AND status IN ('running', 'completed', 'skipped')
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"run_type": run_type, "since": since},
    )
    row = result.fetchone()
    return row is not None


async def fetch_recent_anomaly_findings(session, since: datetime) -> list[tuple[str | None, Any]]:
    """Return ``(metric, structured_data)`` pairs for recent anomaly findings.

    Used by the engine to suppress duplicate anomalies already
    persisted by an earlier rolling check. Returns raw row tuples;
    parsing structured_data into the dedup key is a Python concern
    that lives in the analysis layer.
    """
    result = await session.execute(
        text(
            """
            SELECT metric, structured_data
            FROM analysis_findings
            WHERE finding_type = 'anomaly'
              AND created_at >= :since
            """
        ),
        {"since": since},
    )
    return [(row.metric, row.structured_data) for row in _fetchall(result)]


# ──────────────────────────────────────────────────────────────────
#  Period summaries  (was: analysis.statistical.aggregator)
# ──────────────────────────────────────────────────────────────────


async def hr_summary_from_hourly(session, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate ``hr_hourly`` over ``[start, end)`` into avg/min/max/count."""
    result = await session.execute(
        text(
            """
            SELECT avg(avg_bpm)::float AS avg_v,
                   min(min_bpm) AS min_v,
                   max(max_bpm) AS max_v,
                   sum(samples) AS count_v
            FROM hr_hourly
            WHERE bucket >= :start AND bucket < :end
            """
        ),
        {"start": start, "end": end},
    )
    row = result.fetchone()
    if row is None:
        return {"avg": None, "min": None, "max": None, "count": 0}
    return {
        "avg": row.avg_v,
        "min": row.min_v,
        "max": row.max_v,
        "count": row.count_v or 0,
    }


async def hr_summary_from_raw(session, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate raw ``heart_rate`` rows when ``hr_hourly`` has not refreshed."""
    result = await session.execute(
        text(
            """
            SELECT avg(bpm)::float AS avg_v,
                   min(bpm) AS min_v,
                   max(bpm) AS max_v,
                   count(*) AS count_v
            FROM heart_rate
            WHERE time >= :start AND time < :end
            """
        ),
        {"start": start, "end": end},
    )
    row = result.fetchone()
    if row is None:
        return {"avg": None, "min": None, "max": None, "count": 0}
    return {
        "avg": row.avg_v,
        "min": row.min_v,
        "max": row.max_v,
        "count": row.count_v or 0,
    }


async def hrv_summary(session, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate raw ``hrv`` rows over ``[start, end)`` into avg/min/max/count.

    HRV has no continuous aggregate (Apple Watch records 5-30 samples
    per day) — aggregating the raw hypertable directly is fast enough
    for MVP windows.
    """
    result = await session.execute(
        text(
            """
            SELECT avg(value_ms)::float AS avg_v,
                   min(value_ms) AS min_v,
                   max(value_ms) AS max_v,
                   count(*) AS count_v
            FROM hrv
            WHERE time >= :start AND time < :end
            """
        ),
        {"start": start, "end": end},
    )
    row = result.fetchone()
    if row is None:
        return {"avg": None, "min": None, "max": None, "count": 0}
    return {
        "avg": row.avg_v,
        "min": row.min_v,
        "max": row.max_v,
        "count": row.count_v or 0,
    }


# ──────────────────────────────────────────────────────────────────
#  Anomaly observation fetches  (was: analysis.statistical.anomaly)
# ──────────────────────────────────────────────────────────────────


async def fetch_hr_observations(
    session, start: datetime, end: datetime
) -> list[tuple[datetime, float]]:
    """Return ``(bucket, avg_bpm)`` pairs from ``hr_hourly`` with a raw fallback.

    Falls back to bucketed raw ``heart_rate`` rows when ``hr_hourly``
    is empty (mirrors the aggregator's fallback so the detector stays
    usable on fresh installs).
    """
    result = await session.execute(
        text(
            """
            SELECT bucket, avg_bpm::float AS value
            FROM hr_hourly
            WHERE bucket >= :start AND bucket < :end
              AND avg_bpm IS NOT NULL
            ORDER BY bucket ASC
            """
        ),
        {"start": start, "end": end},
    )
    rows = _fetchall(result)
    if rows:
        return [(row.bucket, float(row.value)) for row in rows if row.value is not None]

    result = await session.execute(
        text(
            """
            SELECT date_trunc('hour', time) AS bucket,
                   avg(bpm)::float AS value
            FROM heart_rate
            WHERE time >= :start AND time < :end
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        ),
        {"start": start, "end": end},
    )
    rows = _fetchall(result)
    return [(row.bucket, float(row.value)) for row in rows if row.value is not None]


async def fetch_hrv_observations(
    session, start: datetime, end: datetime
) -> list[tuple[datetime, float]]:
    """Return ``(time, value_ms)`` pairs from the raw ``hrv`` hypertable."""
    result = await session.execute(
        text(
            """
            SELECT time, value_ms::float AS value
            FROM hrv
            WHERE time >= :start AND time < :end
            ORDER BY time ASC
            """
        ),
        {"start": start, "end": end},
    )
    rows = _fetchall(result)
    return [(row.time, float(row.value)) for row in rows if row.value is not None]


async def fetch_workouts(session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return ``[{start, end}, ...]`` for workouts overlapping the window."""
    result = await session.execute(
        text(
            """
            SELECT start_time, end_time
            FROM workouts
            WHERE start_time <= :end AND end_time >= :start
            ORDER BY start_time ASC
            """
        ),
        {"start": start, "end": end},
    )
    rows = _fetchall(result)
    return [
        {"start": row.start_time, "end": row.end_time}
        for row in rows
        if row.start_time is not None and row.end_time is not None
    ]


# ──────────────────────────────────────────────────────────────────
#  Trend daily-value fetches  (was: analysis.statistical.trends)
# ──────────────────────────────────────────────────────────────────


async def fetch_heart_rate_daily_from_hourly(session, start: datetime, end: datetime) -> list[Any]:
    result = await session.execute(
        text(
            """
            SELECT date_trunc('day', bucket)::date AS day,
                   avg(avg_bpm)::float AS value,
                   sum(samples) AS sample_count
            FROM hr_hourly
            WHERE bucket >= :start AND bucket < :end
              AND avg_bpm IS NOT NULL
            GROUP BY day
            ORDER BY day ASC
            """
        ),
        {"start": start, "end": end},
    )
    return _fetchall(result)


async def fetch_heart_rate_daily_from_raw(session, start: datetime, end: datetime) -> list[Any]:
    result = await session.execute(
        text(
            """
            SELECT date_trunc('day', time)::date AS day,
                   avg(bpm)::float AS value,
                   count(*) AS sample_count
            FROM heart_rate
            WHERE time >= :start AND time < :end
            GROUP BY day
            ORDER BY day ASC
            """
        ),
        {"start": start, "end": end},
    )
    return _fetchall(result)


async def fetch_hrv_daily(session, start: datetime, end: datetime) -> list[Any]:
    result = await session.execute(
        text(
            """
            SELECT date_trunc('day', time)::date AS day,
                   avg(value_ms)::float AS value,
                   count(*) AS sample_count
            FROM hrv
            WHERE time >= :start AND time < :end
            GROUP BY day
            ORDER BY day ASC
            """
        ),
        {"start": start, "end": end},
    )
    return _fetchall(result)


async def fetch_metric_daily_series(
    session,
    metric_id: str,
    start: datetime,
    end: datetime,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
) -> list[Any]:
    """Daily mean of a canonical metric's numeric values over ``[start, end)``.

    Generic over *any* ontology ``metric_id`` — reads the canonical
    Observation store (the ADR-0001 truth), not a per-metric legacy table, so
    the correlation engine isn't limited to the handful of metrics with
    bespoke daily aggregates. Returns rows with ``.day`` (date) and ``.value``
    (float daily mean), ascending; superseded rows are excluded. Owner /
    workspace default to the v1 single-tenant sentinel.
    """
    result = await session.execute(
        text(
            """
            SELECT date_trunc('day', interval_start)::date AS day,
                   avg(numeric_value)::float AS value,
                   count(*) AS sample_count
            FROM canonical_observations
            WHERE owner_id = :owner_id
              AND workspace_id = :workspace_id
              AND metric_id = :metric_id
              AND interval_start >= :start
              AND interval_start < :end
              AND numeric_value IS NOT NULL
              AND status = 'active'
            GROUP BY day
            ORDER BY day ASC
            """
        ),
        {
            "owner_id": str(owner_id),
            "workspace_id": str(workspace_id),
            "metric_id": metric_id,
            "start": start,
            "end": end,
        },
    )
    return _fetchall(result)
