"""TimescaleDB-backed measurement writers.

Phase 5E lifted the per-metric SQL out of ``server.ingestion.handlers``
and ``server.ingestion.sleep`` into this module. The original modules
are now thin re-export shims so existing callers (registry, route,
tests, the catch-all server package re-exports) keep working.

Helpers (parsers, mappers, owner sentinels) stay in
``server.ingestion`` because they're pure-Python domain logic with no
data-access concern. Cross-package import here is acceptable —
the cycle that bit Phase 5C is avoided by not routing through any
``server.__init__`` re-export at module load time:

  storage.timescale.measurements
    → server.ingestion.mappers (sub-package import; runs server.__init__)
       → server.api.ingest (re-export)
         → ..ingestion.storage (shim re-exports from storage.timescale.ingest)
           → storage.timescale.ingest (already loaded by the time we get here
                                        because the timescale __init__
                                        imports `ingest` BEFORE
                                        `measurements`).

Phase 5F may move the helpers themselves out of server.ingestion if a
deeper cleanup is wanted; for v2.0 the shape is fine.
"""

from __future__ import annotations

from datetime import timedelta
from json import dumps
from uuid import UUID

from server.ingestion.mappers import (
    ACTIVITY_FIELDS,
    DAILY_ACTIVITY_QUANTITY_FIELDS,
    DEDICATED_TABLES,
)
from server.ingestion.owner import DEFAULT_OWNER_ID
from server.ingestion.parsers import (
    duration_ms_between,
    first_present,
    parse_date,
    parse_ts,
    to_float,
    to_int,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _sample_source(sample: dict) -> str | None:
    """Extract the source label from a HealthKit-shaped sample.

    HealthSave iOS / Health Sync / Garmin / Whoop normalizers all use
    one of ``source`` / ``sourceName`` / ``source_id`` / ``device`` /
    ``deviceName`` to carry the device-or-app label. Stored as
    ``source_id`` in the metric tables.
    """
    value = first_present(
        sample, "source", "sourceName", "source_id", "device", "deviceName", "device_id"
    )
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _bump_rejected(metric: str, reason: str) -> None:
    """Phase 5G: surface silent sample rejections.

    Pre-5G the ``if t is None or v is None: continue`` pattern in
    every ingest helper threw away malformed samples without any
    counter or warning log. iOS shipping a date-format change would
    look like ``records: 0`` to operators — "nothing to insert"
    when the truth was "every sample failed to parse." Lazy import
    of the counter so this module stays usable from CLI scripts that
    don't load the FastAPI app.
    """
    try:
        from server.api.metrics import INGEST_REJECTED

        INGEST_REJECTED.labels(metric=metric, reason=reason).inc()
    except Exception:  # pragma: no cover - metrics import optional
        # Failing to bump a counter is never a reason to fail ingest.
        pass


# ──────────────────────────────────────────────────────────────────
#  Devices + raw-payload audit log
# ──────────────────────────────────────────────────────────────────


async def _get_or_create_device(session: AsyncSession, device_type: str) -> int:
    result = await session.execute(
        text("SELECT id FROM devices WHERE device_type = :dt"), {"dt": device_type}
    )
    row = result.first()
    if row:
        return row[0]
    result = await session.execute(
        text("INSERT INTO devices (device_type) VALUES (:dt) RETURNING id"),
        {"dt": device_type},
    )
    return result.scalar()


async def _log_raw_ingestion(
    session: AsyncSession, device_id: int | None, raw_payload: dict
) -> int | None:
    result = await session.execute(
        text("""
            INSERT INTO raw_ingestion_log
                (device_id, source_type, endpoint, raw_payload, processed)
            VALUES
                (:device_id, :source_type, :endpoint, CAST(:raw_payload AS jsonb), false)
            RETURNING id
        """),
        {
            "device_id": device_id,
            "source_type": "healthsave",
            "endpoint": "/api/apple/batch",
            "raw_payload": dumps(raw_payload),
        },
    )
    return result.scalar()


async def _mark_raw_ingestion_processed(session: AsyncSession, raw_log_id: int | None) -> None:
    if raw_log_id is None:
        return
    await session.execute(
        text("UPDATE raw_ingestion_log SET processed = true WHERE id = :id"),
        {"id": raw_log_id},
    )


# ──────────────────────────────────────────────────────────────────
#  Per-metric ingest dispatch
# ──────────────────────────────────────────────────────────────────


async def _ingest_metric(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list[dict],
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    """Route a parsed batch to the correct writer.

    Falls back to ``quantity_samples`` (catch-all) when no dedicated
    path exists for the metric.
    """
    if metric == "activity_summaries":
        return await _ingest_activity(session, device_id, samples, owner_id=owner_id)
    if metric in DAILY_ACTIVITY_QUANTITY_FIELDS:
        return await _ingest_daily_quantity(session, device_id, metric, samples, owner_id=owner_id)
    if metric == "sleep_analysis":
        return await _ingest_sleep(session, device_id, samples, owner_id=owner_id)
    if metric == "workouts":
        return await _ingest_workouts(session, device_id, samples, owner_id=owner_id)
    if metric in DEDICATED_TABLES:
        return await _ingest_dedicated(session, device_id, metric, samples, owner_id=owner_id)
    return await _ingest_generic(session, device_id, metric, samples, owner_id=owner_id)


async def _ingest_dedicated(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    spec = DEDICATED_TABLES[metric]
    rows = []
    value_col = list(spec["columns"].values())[1]
    for s in samples:
        row = {"device_id": device_id, "owner_id": str(owner_id)}
        for src_key, dst_col in spec["columns"].items():
            val = s.get(src_key)
            if dst_col == "time":
                val = parse_ts(val)
            if dst_col in spec.get("transforms", {}):
                val = spec["transforms"][dst_col](val)
            row[dst_col] = val
        if "defaults" in spec:
            row.update(spec["defaults"])
        if row.get("time") and row.get(value_col) is not None:
            rows.append(row)
        else:
            _bump_rejected(metric, "missing_time_or_value")

    if not rows:
        return 0

    # Dedup within batch (conflict_cols already include owner_id via the schema)
    conflict_cols = list(spec["conflict"]) + ["owner_id"]
    seen = {}
    for row in rows:
        key = tuple(row.get(c) for c in conflict_cols)
        seen[key] = row
    rows = list(seen.values())

    conflict_sql = ", ".join(conflict_cols)
    col_names = ", ".join(rows[0].keys())
    placeholders = ", ".join(f":{k}" for k in rows[0])
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in rows[0] if c not in conflict_cols)

    sql = f"""
        INSERT INTO {spec["table"]} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_set}
    """

    for row in rows:
        await session.execute(text(sql), row)

    return len(rows)


async def _ingest_generic(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    """Insert into the catch-all quantity_samples table."""
    count = 0
    for s in samples:
        t = parse_ts(s.get("date"))
        v = to_float(s.get("qty"))
        if t is None or v is None:
            _bump_rejected(metric, "missing_or_unparseable_date_or_qty")
            continue
        sample_metric = s.get("metric") if isinstance(s.get("metric"), str) else metric
        await session.execute(
            text("""
                INSERT INTO quantity_samples
                    (time, device_id, metric_name, value, unit, source_id, owner_id)
                VALUES (:time, :device_id, :metric, :value, :unit, :source, :owner_id)
                ON CONFLICT (time, device_id, metric_name, owner_id) DO UPDATE
                SET value = EXCLUDED.value, unit = EXCLUDED.unit
            """),
            {
                "time": t,
                "device_id": device_id,
                "metric": sample_metric,
                "value": v,
                "unit": s.get("unit", ""),
                "source": s.get("source", ""),
                "owner_id": str(owner_id),
            },
        )
        count += 1
    return count


async def _ingest_activity(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    count = 0
    for s in samples:
        d = parse_date(s.get("date"))
        if not d:
            _bump_rejected("activity_summaries", "missing_or_unparseable_date")
            continue

        row = {"date": d, "device_id": device_id, "owner_id": str(owner_id)}
        for src_key, dst_col in ACTIVITY_FIELDS.items():
            if src_key in s:
                row[dst_col] = s[src_key]
        source_id = _sample_source(s)
        if source_id is not None:
            row["source_id"] = source_id

        cols = ", ".join(row.keys())
        vals = ", ".join(f":{k}" for k in row)
        updates = ", ".join(
            f"{k} = COALESCE(EXCLUDED.{k}, daily_activity.{k})"
            for k in row
            if k not in ("date", "device_id", "owner_id")
        )

        await session.execute(
            text(f"""
                INSERT INTO daily_activity ({cols}) VALUES ({vals})
                ON CONFLICT (date, device_id, owner_id) DO UPDATE SET {updates}
            """),
            row,
        )
        count += 1
    return count


async def _ingest_daily_quantity(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    column, converter = DAILY_ACTIVITY_QUANTITY_FIELDS[metric]
    count = 0
    for sample in samples:
        d = parse_date(sample.get("date"))
        value = converter(sample.get("qty"))
        if not d or value is None:
            _bump_rejected(metric, "missing_or_unparseable_date_or_qty")
            continue

        source_id = _sample_source(sample)
        await session.execute(
            text(f"""
                INSERT INTO daily_activity (date, device_id, owner_id, source_id, {column})
                VALUES (:date, :device_id, :owner_id, :source_id, :{column})
                ON CONFLICT (date, device_id, owner_id) DO UPDATE
                SET {column} = EXCLUDED.{column},
                    source_id = COALESCE(EXCLUDED.source_id, daily_activity.source_id)
            """),
            {
                "date": d,
                "device_id": device_id,
                "owner_id": str(owner_id),
                "source_id": source_id,
                column: value,
            },
        )
        count += 1
    return count


async def _ingest_workouts(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    count = 0
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "start", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate", "end"))
        if not start or not end:
            _bump_rejected("workouts", "missing_or_unparseable_start_or_end")
            continue
        duration_ms = first_present(s, "duration_ms")
        if duration_ms is None:
            duration_seconds = to_float(first_present(s, "duration"))
            duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else None
        else:
            duration_ms = to_int(duration_ms)
        await session.execute(
            text("""
                INSERT INTO workouts (device_id, sport_type, start_time, end_time,
                    duration_ms, avg_hr, max_hr, calories, distance_m, source_id, owner_id)
                VALUES (:device_id, :sport, :start, :end, :dur, :avg_hr, :max_hr, :cal, :dist,
                    :source_id, :owner_id)
                ON CONFLICT (device_id, start_time, owner_id) DO UPDATE SET
                    sport_type = EXCLUDED.sport_type,
                    end_time = EXCLUDED.end_time,
                    duration_ms = EXCLUDED.duration_ms,
                    avg_hr = EXCLUDED.avg_hr,
                    max_hr = EXCLUDED.max_hr,
                    calories = EXCLUDED.calories,
                    distance_m = EXCLUDED.distance_m,
                    source_id = COALESCE(EXCLUDED.source_id, workouts.source_id)
            """),
            {
                "device_id": device_id,
                "sport": first_present(s, "sport_type", "sportType", "name") or "unknown",
                "start": start,
                "end": end,
                "dur": duration_ms,
                "avg_hr": to_float(first_present(s, "avg_hr", "avgHeartRate")),
                "max_hr": to_float(first_present(s, "max_hr", "maxHeartRate")),
                "cal": to_float(first_present(s, "calories", "activeEnergy")),
                "dist": to_float(first_present(s, "distance_m", "distance")),
                "source_id": _sample_source(s),
                "owner_id": str(owner_id),
            },
        )
        count += 1
    return count


# ──────────────────────────────────────────────────────────────────
#  Sleep — segment grouping + session/stage upserts
# ──────────────────────────────────────────────────────────────────


def sleep_stage_segments(samples: list[dict]) -> list[dict]:
    segments = []
    for sample in samples:
        start = parse_ts(first_present(sample, "start_date", "startDate", "start", "date"))
        end = parse_ts(first_present(sample, "end_date", "endDate", "end"))
        if not start or not end or end <= start:
            continue
        segments.append(
            {
                "start": start,
                "end": end,
                "stage": str(first_present(sample, "value", "stage") or "").strip().lower(),
                "source": _sample_source(sample),
            }
        )

    segments.sort(key=lambda segment: segment["start"])
    return segments


def sleep_session_rows(device_id: int, samples: list[dict]) -> list[dict]:
    """Aggregate HealthKit sleep stage samples into session rows."""
    segments = sleep_stage_segments(samples)
    if not segments:
        return []

    sessions = []
    gap_threshold = timedelta(hours=4)
    current = None

    for segment in segments:
        start = segment["start"]
        end = segment["end"]

        if current is None or start - current["last_end"] > gap_threshold:
            if current is not None:
                sessions.append(current)
            current = {
                "start": start,
                "end": end,
                "last_end": end,
                "deep_ms": 0,
                "rem_ms": 0,
                "light_ms": 0,
                "awake_ms": 0,
                "segments": [],
            }
        else:
            current["end"] = max(current["end"], end)
            current["last_end"] = max(current["last_end"], end)

        current["segments"].append(segment)

        bucket = None
        if segment["stage"] == "deep":
            bucket = "deep_ms"
        elif segment["stage"] == "rem":
            bucket = "rem_ms"
        elif segment["stage"] == "awake":
            bucket = "awake_ms"
        elif segment["stage"] in {"core", "light", "asleep", "asleep unspecified"}:
            bucket = "light_ms"

        if bucket:
            current[bucket] += duration_ms_between(start, end)

    if current is not None:
        sessions.append(current)

    rows = []
    for session in sessions:
        total_duration_ms = session["deep_ms"] + session["rem_ms"] + session["light_ms"]
        if total_duration_ms == 0 and session["awake_ms"] == 0:
            continue
        # Pick the first non-null source from the session's segments.
        # In practice all segments share a source (single watch logging
        # one night of sleep); this guards against mixed-source noise.
        source_id = next(
            (seg.get("source") for seg in session["segments"] if seg.get("source")),
            None,
        )
        rows.append(
            {
                "device_id": device_id,
                "start": session["start"],
                "end": session["end"],
                "total": total_duration_ms,
                "deep": session["deep_ms"],
                "rem": session["rem_ms"],
                "light": session["light_ms"],
                "awake": session["awake_ms"],
                "rr": None,
                "source_id": source_id,
                "segments": session["segments"],
            }
        )
    return rows


async def _upsert_sleep_session(session: AsyncSession, row: dict) -> int:
    row.setdefault("owner_id", str(DEFAULT_OWNER_ID))
    row.setdefault("source_id", None)
    result = await session.execute(
        text("""
            INSERT INTO sleep_sessions (device_id, start_time, end_time, total_duration_ms,
                deep_ms, rem_ms, light_ms, awake_ms, respiratory_rate, owner_id, source_id)
            VALUES (:device_id, :start, :end, :total, :deep, :rem, :light, :awake, :rr,
                :owner_id, :source_id)
            ON CONFLICT (device_id, start_time, owner_id) DO UPDATE SET
                end_time = EXCLUDED.end_time,
                total_duration_ms = EXCLUDED.total_duration_ms,
                deep_ms = EXCLUDED.deep_ms,
                rem_ms = EXCLUDED.rem_ms,
                light_ms = EXCLUDED.light_ms,
                awake_ms = EXCLUDED.awake_ms,
                respiratory_rate = EXCLUDED.respiratory_rate,
                source_id = COALESCE(EXCLUDED.source_id, sleep_sessions.source_id)
            RETURNING id
        """),
        row,
    )
    return result.scalar()


async def _upsert_sleep_stages(
    session: AsyncSession,
    device_id: int,
    session_id: int | None,
    segments: list[dict],
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> None:
    for segment in segments:
        duration_ms = duration_ms_between(segment["start"], segment["end"])
        if duration_ms <= 0:
            continue
        await session.execute(
            text("""
                INSERT INTO sleep_stages
                    (time, device_id, session_id, stage, duration_ms, owner_id)
                VALUES (:time, :device_id, :session_id, :stage, :duration_ms, :owner_id)
                ON CONFLICT (time, device_id, stage, owner_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    duration_ms = EXCLUDED.duration_ms
            """),
            {
                "time": segment["start"],
                "device_id": device_id,
                "session_id": session_id,
                "stage": segment["stage"],
                "duration_ms": duration_ms,
                "owner_id": str(owner_id),
            },
        )


async def ingest_sleep(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> int:
    if any("startDate" in sample or "value" in sample for sample in samples):
        rows = sleep_session_rows(device_id, samples)
        count = 0
        for row in rows:
            segments = row.pop("segments", [])
            row["owner_id"] = str(owner_id)
            session_id = await _upsert_sleep_session(session, row)
            await _upsert_sleep_stages(session, device_id, session_id, segments, owner_id=owner_id)
            count += 1
        return count

    count = 0
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate"))
        if not start or not end:
            _bump_rejected("sleep_analysis", "missing_or_unparseable_start_or_end")
            continue
        await _upsert_sleep_session(
            session,
            {
                "device_id": device_id,
                "start": start,
                "end": end,
                "total": to_int(s.get("total_duration_ms")),
                "deep": to_int(s.get("deep_ms")),
                "rem": to_int(s.get("rem_ms")),
                "light": to_int(s.get("light_ms") or s.get("core_ms")),
                "awake": to_int(s.get("awake_ms")),
                "rr": to_float(s.get("respiratory_rate")),
                "owner_id": str(owner_id),
            },
        )
        count += 1
    return count


# Historical private alias preserved for the dispatch table in this
# module + any external callers that reach in via attribute access.
_ingest_sleep = ingest_sleep


# ──────────────────────────────────────────────────────────────────
#  Phase-5C MeasurementRepository class skeleton kept as a name —
#  Phase 5F may attach methods (insert_heart_rate, insert_workout,
#  fetch_series). Today the class is empty; the SQL above is the
#  shipped surface and module-level functions are how callers reach
#  it.
# ──────────────────────────────────────────────────────────────────


class TimescaleMeasurementRepository:
    """Skeleton for the eventual Protocol-style class. Today the
    public surface is the module-level functions above; future phases
    may bind them as methods if injection is wanted."""


default_repository = TimescaleMeasurementRepository()
