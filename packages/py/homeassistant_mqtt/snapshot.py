"""Pure snapshot helpers for the Home Assistant MQTT bridge."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HealthSnapshot:
    collected_at: datetime
    heart_rate: int | None
    hrv_7d_avg: float | None
    steps_today: int | None
    last_sleep_hours: float | None
    source_model: str
    room_health_state: str | None


def latest_non_null(rows: Sequence[Sequence[Any]], default: Any = None) -> Any:
    """Return the first non-null first-column value from row-like results."""

    for row in rows:
        if row and row[0] is not None:
            return row[0]
    return default


def round_float(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def derive_room_health_state(snapshot: HealthSnapshot) -> str:
    """Small deterministic state for dashboards/automations.

    This is intentionally simple: Home Assistant should receive a stable
    high-level state, while deeper analytics stay in Grafana/analysis tables.
    """

    if snapshot.last_sleep_hours is not None and snapshot.last_sleep_hours < 5:
        return "sleep_debt"
    if snapshot.hrv_7d_avg is not None and snapshot.hrv_7d_avg < 30:
        return "recovery"
    if snapshot.steps_today is not None and snapshot.steps_today >= 8000:
        return "active"
    return "normal"
