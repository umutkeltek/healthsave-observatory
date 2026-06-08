"""Primitive sample-level parsers shared by every ingestion path.

ARCH-001: these pure helpers live below the storage layer so storage writers can
use them without an upward import on the API package. The API layer + plugins
reach them via the ``server.ingestion.parsers`` re-export shim.
"""

import math
from datetime import UTC, date, datetime


def to_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result):
        return None
    return result


def to_int(value) -> int | None:
    numeric = to_float(value)
    return int(numeric) if numeric is not None else None


def normalize_blood_oxygen(value) -> float | None:
    numeric = to_float(value)
    if numeric is None:
        return None
    return numeric * 100 if 0 <= numeric <= 1 else numeric


def parse_ts(value: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp string to datetime. asyncpg needs real objects.

    DATA-001: the wire contract is ISO 8601 with a trailing ``Z`` (UTC); if a
    value arrives WITHOUT an offset we assume UTC and attach it, so a naive
    datetime is never written into a TIMESTAMPTZ column (where Postgres would
    otherwise interpret it against the session TimeZone and silently shift it).
    No-op for the normal ``Z`` path, which is already tz-aware.
    """
    if not value:
        return None
    try:
        # Handle Z suffix and various ISO formats
        s = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_date(value: str | None) -> date | None:
    """Parse date string (YYYY-MM-DD or ISO timestamp) to date object."""
    if not value:
        return None
    try:
        if "T" in value:
            parsed = parse_ts(value)
            return parsed.date() if parsed else None
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
