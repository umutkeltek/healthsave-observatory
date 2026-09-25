"""Wire rules for ``heartbeat_series``: the beats behind an Apple Watch HRV reading.

HealthKit keeps, next to most Apple Watch HRV (SDNN) readings, the heartbeat
series the reading was computed from (``HKHeartbeatSeriesSample``): for every
beat, its offset in seconds from the series' ``startDate`` and whether a gap in
collection came before it. SDNN is one number per reading; the same value can
come from steady variability, from a missed stretch, or from a heart rate that
changed during the minute, and only the beat list tells them apart.

HealthSave iOS sends one sample per series (opt-in, v2 wire)::

    {"uuid": "...", "startDate": "...", "endDate": "...", "tzOffsetMinutes": -240,
     "source": "Apple Watch", "hrvUUID": "<uuid of the HRV sample, when found>",
     "heartbeats": [{"timeSinceStart": 0.0, "precededByGap": false}, ...]}

``hrvUUID`` is present only when exactly one HRV sample from the same source
shares the series' interval at read time; the interval itself always ties the
two together.

There is no v1 table for this metric. The canonical store keeps the whole sample
(the beat list rides in the event's ``summary``) and the v1 writer only
validates and counts, so both paths use this one rule and cannot disagree about
what a valid sample is.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from normalization.parsers import parse_ts

HEARTBEAT_SERIES_WIRE_METRIC = "heartbeat_series"

_START_KEYS = ("startDate", "start", "date")


def heartbeat_series_problem(sample: Mapping[str, Any]) -> str | None:
    """The rejection reason for ``sample``, or ``None`` when it is a usable series."""

    start = next((sample[key] for key in _START_KEYS if sample.get(key) is not None), None)
    if parse_ts(start) is None:
        return "missing_or_unparseable_time"

    beats = sample.get("heartbeats")
    if not isinstance(beats, list):
        return "missing_heartbeats"
    for beat in beats:
        if not isinstance(beat, Mapping):
            return "invalid_heartbeat"
        offset = beat.get("timeSinceStart")
        # bool is an int subclass; a flag in the offset slot is a malformed beat.
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int | float)
            or not math.isfinite(offset)
            or offset < 0
        ):
            return "invalid_heartbeat_offset"
        if not isinstance(beat.get("precededByGap"), bool):
            return "invalid_heartbeat_gap_flag"

    hrv_uuid = sample.get("hrvUUID")
    if hrv_uuid is not None and not _is_uuid(hrv_uuid):
        return "invalid_hrv_uuid"
    return None


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True
