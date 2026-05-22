"""Pure snapshot helpers for the Home Assistant MQTT bridge.

Two snapshot shapes coexist:

  * :class:`HealthSnapshot` — the legacy aggregate snapshot (one row of
    latest-across-all-sources values). The current bridge consumes this
    and publishes one HA device.
  * :class:`SourceHealthSnapshot` — per-``source_id`` latest values for
    the metrics that actually carry source attribution (``heart_rate``,
    ``hrv``). The forthcoming source-aware bridge consumes a list of
    these and publishes one HA sub-device per source via the
    ``via_device`` pattern.

``source_slug`` normalizes free-form source labels (``"Apple Watch"``,
``"Umut's iPhone"``) into MQTT-topic-safe slugs (``"apple_watch"``,
``"umut_s_iphone"``). The bridge feeds the slug into both the discovery
topic and the per-source state topic so HA picks up a clean entity id.
"""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class SourceHealthSnapshot:
    """Latest values for one ``source_id`` across all source-tagged metrics.

    Migration 009 added ``source_id`` to ``daily_activity`` and
    ``sleep_sessions`` so every primary metric (HR, HRV, steps, sleep)
    can be queried per source. The HA-side mapping: one sub-device per
    distinct source slug emits all four metrics.

    A field is ``None`` when the source has no recent row for that
    metric — common for body-comp scales (steps only), iPhones (HR but
    no sleep), etc. The bridge skips ``None`` values when building
    state payloads so HA never receives a stale or zero entity.
    """

    collected_at: datetime
    source_id: str
    heart_rate: int | None
    hrv_latest_ms: float | None
    steps_today: int | None = None
    last_sleep_hours: float | None = None

    @property
    def slug(self) -> str:
        """MQTT/HA-topic-safe identifier derived from ``source_id``."""

        return source_slug(self.source_id)


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_DEDUP = re.compile(r"_+")


def source_slug(source_id: str | None) -> str:
    """Normalize a free-form source label into a slug safe for MQTT
    topics + HA entity ids.

      * Lowercase.
      * Any non-alphanumeric run collapses to a single ``_``.
      * Leading and trailing ``_`` stripped.
      * Empty / None / whitespace-only -> ``"unknown"``.

    >>> source_slug("Apple Watch")
    'apple_watch'
    >>> source_slug("Umut's iPhone")
    'umut_s_iphone'
    >>> source_slug(None)
    'unknown'
    """
    if not source_id:
        return "unknown"
    lowered = source_id.lower().strip()
    if not lowered:
        return "unknown"
    cleaned = _SLUG_NON_ALNUM.sub("_", lowered)
    cleaned = _SLUG_DEDUP.sub("_", cleaned).strip("_")
    return cleaned or "unknown"


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
