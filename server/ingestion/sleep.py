"""Sleep ingestion: stage segmentation, session aggregation, and upserts.

Owns the two sleep-table writers (``_upsert_sleep_session`` and
``_upsert_sleep_stages``) because they are only ever called from this
module's ``ingest_sleep`` dispatch path.
"""

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .parsers import duration_ms_between, first_present, parse_ts, to_float, to_int


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


async def ingest_sleep(session: AsyncSession, device_id: int, samples: list) -> int:
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
