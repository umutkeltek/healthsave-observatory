"""
Health Data Hub

Minimal FastAPI server that receives health data from a compatible client
such as the HealthSave iOS app and stores it in TimescaleDB. HealthSave
expects a base server URL like http://your-server:8000 and appends the batch
endpoint itself.

Env vars:
    DATABASE_URL  - PostgreSQL connection string (default: see below)
    API_KEY       - Optional API key for authentication (leave empty to disable)
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from json import dumps
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

log = logging.getLogger("healthsave")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://healthsave:changeme@db:5432/healthsave",
)
API_KEY = os.getenv("API_KEY", "")

engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class BatchPayload(BaseModel):
    metric: str = "unknown"
    batch_index: int = Field(default=0)
    total_batches: int = Field(default=1)
    samples: list[dict[str, Any]] = Field(default_factory=list)


async def get_session():
    async with async_session() as session:
        yield session


def verify_api_key(x_api_key: str = Header(default="")):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value) -> int | None:
    numeric = to_float(value)
    return int(numeric) if numeric is not None else None


def normalize_blood_oxygen(value) -> float | None:
    numeric = to_float(value)
    if numeric is None:
        return None
    return numeric * 100 if 0 <= numeric <= 1 else numeric


# ─── Metric → Table Mapping ──────────────────────────────────────────

# Metrics that map to dedicated tables with specific column mappings
DEDICATED_TABLES = {
    "heart_rate": {
        "table": "heart_rate",
        "columns": {"date": "time", "qty": "bpm", "source": "source_id"},
        "transforms": {"bpm": to_int},
        "conflict": ["time", "device_id"],
    },
    "heart_rate_variability": {
        "table": "hrv",
        "columns": {"date": "time", "qty": "value_ms", "source": "source_id"},
        "transforms": {"value_ms": to_float},
        "defaults": {"algorithm": "sdnn"},
        "conflict": ["time", "device_id"],
    },
    "blood_oxygen": {
        "table": "blood_oxygen",
        "columns": {"date": "time", "qty": "spo2_pct"},
        "transforms": {"spo2_pct": normalize_blood_oxygen},
        "conflict": ["time", "device_id"],
    },
    "oxygen_saturation": {
        "table": "blood_oxygen",
        "columns": {"date": "time", "qty": "spo2_pct"},
        "transforms": {"spo2_pct": normalize_blood_oxygen},
        "conflict": ["time", "device_id"],
    },
    "body_temperature": {
        "table": "body_temperature",
        "columns": {"date": "time", "qty": "temp_celsius"},
        "transforms": {"temp_celsius": to_float},
        "conflict": ["time", "device_id"],
    },
    "wrist_temperature": {
        "table": "body_temperature",
        "columns": {"date": "time", "qty": "temp_celsius"},
        "transforms": {"temp_celsius": to_float},
        "conflict": ["time", "device_id"],
    },
}

# Activity summary fields → daily_activity columns
ACTIVITY_FIELDS = {
    "steps": "steps",
    "distance": "distance_m",
    "flights_climbed": "floors_climbed",
    "active_energy": "active_calories",
    "activeEnergyBurned": "active_calories",
    "basal_energy": "total_calories",
    "exercise_minutes": "active_minutes",
    "appleExerciseTime": "active_minutes",
    "stand_hours": "stand_hours",
    "appleStandHours": "stand_hours",
}

# HealthSave sends many activity totals as quantity batches rather than as
# `activity_summaries`; keep Grafana-facing daily totals populated.
DAILY_ACTIVITY_QUANTITY_FIELDS = {
    "step_count": ("steps", to_int),
    "distance_walking_running": ("distance_m", to_float),
    "flights_climbed": ("floors_climbed", to_int),
    "active_energy_burned": ("active_calories", to_float),
    "basal_energy_burned": ("total_calories", to_float),
    "apple_exercise_time": ("active_minutes", to_int),
}


@asynccontextmanager
async def lifespan(a: FastAPI):
    log.info("HealthSave server starting")
    yield
    await engine.dispose()


app = FastAPI(title="Health Data Hub", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("Readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@app.post("/api/apple/batch", dependencies=[Depends(verify_api_key)])
async def apple_batch(request: Request, session: AsyncSession = Depends(get_session)):
    """Receive a metric batch from HealthSave iOS app.

    Expected payload:
    {
        "metric": "heart_rate",
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {"date": "2024-01-15T10:30:00Z", "qty": 72, "source": "Apple Watch"},
            ...
        ]
    }
    """
    raw_payload = await request.json()
    try:
        payload = BatchPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    metric = payload.metric.strip() or "unknown"
    batch_idx = payload.batch_index
    total = payload.total_batches
    samples = payload.samples

    if not samples:
        raw_log_id = await _log_raw_ingestion(session, None, raw_payload)
        await session.commit()
        await _mark_raw_ingestion_processed(session, raw_log_id)
        await session.commit()
        return {"status": "empty", "metric": metric, "batch": batch_idx, "records": 0}

    sample_groups = group_samples_by_device(samples)
    first_device_name, _ = sample_groups[0]
    first_device_id = await _get_or_create_device(session, first_device_name)
    raw_log_id = await _log_raw_ingestion(session, first_device_id, raw_payload)
    await session.commit()
    count = 0

    for device_name, device_samples in sample_groups:
        device_id = (
            first_device_id
            if device_name == first_device_name
            else await _get_or_create_device(session, device_name)
        )
        count += await _ingest_metric(session, device_id, metric, device_samples)

    await _mark_raw_ingestion_processed(session, raw_log_id)
    await session.commit()
    log.info(f"Ingested {count} records for {metric} (batch {batch_idx + 1}/{total})")

    return {
        "status": "processed",
        "metric": metric,
        "batch": batch_idx,
        "total_batches": total,
        "records": count,
    }


@app.get("/api/apple/status", dependencies=[Depends(verify_api_key)])
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


# ─── Date Parsing ─────────────────────────────────────────────────────


def parse_ts(value: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp string to datetime. asyncpg needs real objects."""
    if not value:
        return None
    try:
        # Handle Z suffix and various ISO formats
        s = value.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def parse_date(value: str | None) -> date | None:
    """Parse date string (YYYY-MM-DD or ISO timestamp) to date object."""
    if not value:
        return None
    try:
        if "T" in value:
            return parse_ts(value).date() if parse_ts(value) else None
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def first_present(sample: dict, *keys: str):
    for key in keys:
        value = sample.get(key)
        if value is not None:
            return value
    return None


def sample_device_name(sample: dict) -> str:
    value = first_present(
        sample,
        "source",
        "source_id",
        "sourceName",
        "device",
        "deviceName",
        "device_id",
    )
    if value is None:
        return "HealthSave"
    name = str(value).strip()
    return name or "HealthSave"


def group_samples_by_device(samples: list[dict]) -> list[tuple[str, list[dict]]]:
    grouped: dict[str, list[dict]] = {}
    for sample in samples:
        grouped.setdefault(sample_device_name(sample), []).append(sample)
    return list(grouped.items())


def duration_ms_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() * 1000))


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
                "segments": session["segments"],
            }
        )
    return rows


# ─── Ingestion Helpers ────────────────────────────────────────────────


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


async def _ingest_sleep(session: AsyncSession, device_id: int, samples: list) -> int:
    if any("startDate" in sample or "value" in sample for sample in samples):
        rows = sleep_session_rows(device_id, samples)
        count = 0
        for row in rows:
            segments = row.pop("segments", [])
            session_id = await _upsert_sleep_session(session, row)
            await _upsert_sleep_stages(session, device_id, session_id, segments)
            count += 1
        return count

    count = 0
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate"))
        if not start or not end:
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
            },
        )
        count += 1
    return count


async def _upsert_sleep_session(session: AsyncSession, row: dict) -> int:
    result = await session.execute(
        text("""
            INSERT INTO sleep_sessions (device_id, start_time, end_time, total_duration_ms,
                deep_ms, rem_ms, light_ms, awake_ms, respiratory_rate)
            VALUES (:device_id, :start, :end, :total, :deep, :rem, :light, :awake, :rr)
            ON CONFLICT (device_id, start_time) DO UPDATE SET
                end_time = EXCLUDED.end_time,
                total_duration_ms = EXCLUDED.total_duration_ms,
                deep_ms = EXCLUDED.deep_ms,
                rem_ms = EXCLUDED.rem_ms,
                light_ms = EXCLUDED.light_ms,
                awake_ms = EXCLUDED.awake_ms,
                respiratory_rate = EXCLUDED.respiratory_rate
            RETURNING id
        """),
        row,
    )
    return result.scalar()


async def _upsert_sleep_stages(
    session: AsyncSession, device_id: int, session_id: int | None, segments: list[dict]
) -> None:
    for segment in segments:
        duration_ms = duration_ms_between(segment["start"], segment["end"])
        if duration_ms <= 0:
            continue
        await session.execute(
            text("""
                INSERT INTO sleep_stages (time, device_id, session_id, stage, duration_ms)
                VALUES (:time, :device_id, :session_id, :stage, :duration_ms)
                ON CONFLICT (time, device_id, stage) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    duration_ms = EXCLUDED.duration_ms
            """),
            {
                "time": segment["start"],
                "device_id": device_id,
                "session_id": session_id,
                "stage": segment["stage"],
                "duration_ms": duration_ms,
            },
        )


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
