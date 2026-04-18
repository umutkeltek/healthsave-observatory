"""Ingestion dispatch + per-table writers.

The ``_ingest_metric`` dispatcher routes a parsed batch to the correct
writer based on the metric name, falling back to the catch-all
``quantity_samples`` table when no dedicated path exists.

``_ingest_sleep`` is a thin alias to :func:`server.ingestion.sleep.ingest_sleep`
so that the existing private dispatch table keeps working unchanged.
"""

from json import dumps

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .mappers import ACTIVITY_FIELDS, DAILY_ACTIVITY_QUANTITY_FIELDS, DEDICATED_TABLES
from .parsers import first_present, parse_date, parse_ts, to_float, to_int
from .sleep import ingest_sleep

# Preserve the historical private name so internal callers (and any local
# patches that reach in) continue to resolve.
_ingest_sleep = ingest_sleep


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


async def _ingest_metric(
    session: AsyncSession, device_id: int, metric: str, samples: list[dict]
) -> int:
    if metric == "activity_summaries":
        return await _ingest_activity(session, device_id, samples)
    if metric in DAILY_ACTIVITY_QUANTITY_FIELDS:
        return await _ingest_daily_quantity(session, device_id, metric, samples)
    if metric == "sleep_analysis":
        return await _ingest_sleep(session, device_id, samples)
    if metric == "workouts":
        return await _ingest_workouts(session, device_id, samples)
    if metric in DEDICATED_TABLES:
        return await _ingest_dedicated(session, device_id, metric, samples)
    return await _ingest_generic(session, device_id, metric, samples)


async def _ingest_dedicated(
    session: AsyncSession, device_id: int, metric: str, samples: list
) -> int:
    spec = DEDICATED_TABLES[metric]
    rows = []
    value_col = list(spec["columns"].values())[1]
    for s in samples:
        row = {"device_id": device_id}
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

    if not rows:
        return 0

    # Dedup within batch
    seen = {}
    for row in rows:
        key = tuple(row.get(c) for c in spec["conflict"])
        seen[key] = row
    rows = list(seen.values())

    conflict_cols = ", ".join(spec["conflict"])
    col_names = ", ".join(rows[0].keys())
    placeholders = ", ".join(f":{k}" for k in rows[0])
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in rows[0] if c not in spec["conflict"])

    sql = f"""
        INSERT INTO {spec["table"]} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}
    """

    for row in rows:
        await session.execute(text(sql), row)

    return len(rows)


async def _ingest_generic(session: AsyncSession, device_id: int, metric: str, samples: list) -> int:
    """Insert into the catch-all quantity_samples table."""
    count = 0
    for s in samples:
        t = parse_ts(s.get("date"))
        v = to_float(s.get("qty"))
        if t is None or v is None:
            continue
        sample_metric = s.get("metric") if isinstance(s.get("metric"), str) else metric
        await session.execute(
            text("""
                INSERT INTO quantity_samples (time, device_id, metric_name, value, unit, source_id)
                VALUES (:time, :device_id, :metric, :value, :unit, :source)
                ON CONFLICT (time, device_id, metric_name) DO UPDATE
                SET value = EXCLUDED.value, unit = EXCLUDED.unit
            """),
            {
                "time": t,
                "device_id": device_id,
                "metric": sample_metric,
                "value": v,
                "unit": s.get("unit", ""),
                "source": s.get("source", ""),
            },
        )
        count += 1
    return count


async def _ingest_activity(session: AsyncSession, device_id: int, samples: list) -> int:
    count = 0
    for s in samples:
        d = parse_date(s.get("date"))
        if not d:
            continue

        row = {"date": d, "device_id": device_id}
        for src_key, dst_col in ACTIVITY_FIELDS.items():
            if src_key in s:
                row[dst_col] = s[src_key]

        cols = ", ".join(row.keys())
        vals = ", ".join(f":{k}" for k in row)
        updates = ", ".join(
            f"{k} = COALESCE(EXCLUDED.{k}, daily_activity.{k})"
            for k in row
            if k not in ("date", "device_id")
        )

        await session.execute(
            text(f"""
                INSERT INTO daily_activity ({cols}) VALUES ({vals})
                ON CONFLICT (date, device_id) DO UPDATE SET {updates}
            """),
            row,
        )
        count += 1
    return count


async def _ingest_daily_quantity(
    session: AsyncSession, device_id: int, metric: str, samples: list
) -> int:
    column, converter = DAILY_ACTIVITY_QUANTITY_FIELDS[metric]
    count = 0
    for sample in samples:
        d = parse_date(sample.get("date"))
        value = converter(sample.get("qty"))
        if not d or value is None:
            continue

        await session.execute(
            text(f"""
                INSERT INTO daily_activity (date, device_id, {column})
                VALUES (:date, :device_id, :{column})
                ON CONFLICT (date, device_id) DO UPDATE
                SET {column} = EXCLUDED.{column}
            """),
            {"date": d, "device_id": device_id, column: value},
        )
        count += 1
    return count


async def _ingest_workouts(session: AsyncSession, device_id: int, samples: list) -> int:
    count = 0
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "start", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate", "end"))
        if not start or not end:
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
                    duration_ms, avg_hr, max_hr, calories, distance_m)
                VALUES (:device_id, :sport, :start, :end, :dur, :avg_hr, :max_hr, :cal, :dist)
                ON CONFLICT (device_id, start_time) DO UPDATE SET
                    sport_type = EXCLUDED.sport_type,
                    end_time = EXCLUDED.end_time,
                    duration_ms = EXCLUDED.duration_ms,
                    avg_hr = EXCLUDED.avg_hr,
                    max_hr = EXCLUDED.max_hr,
                    calories = EXCLUDED.calories,
                    distance_m = EXCLUDED.distance_m
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
            },
        )
        count += 1
    return count
