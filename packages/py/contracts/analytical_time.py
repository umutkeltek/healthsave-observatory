"""Person-local calendar semantics for derived health analysis.

Observation timestamps remain absolute instants. This contract only decides
which *analytical day* an instant belongs to. A configurable boundary (04:00 by
default) prevents after-midnight sleep and late-night behavior from being split
across civil dates. Sleep sessions are assigned from their wake/end instant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIME_ZONE = "UTC"
DEFAULT_DAY_BOUNDARY_MINUTES = 4 * 60
MIN_DAY_BOUNDARY_MINUTES = 0
MAX_DAY_BOUNDARY_MINUTES = 12 * 60


@dataclass(frozen=True, slots=True)
class AnalyticalTime:
    time_zone: str = DEFAULT_TIME_ZONE
    day_boundary_minutes: int = DEFAULT_DAY_BOUNDARY_MINUTES

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA time zone: {self.time_zone}") from error
        if not MIN_DAY_BOUNDARY_MINUTES <= self.day_boundary_minutes <= MAX_DAY_BOUNDARY_MINUTES:
            raise ValueError(
                "day_boundary_minutes must be between "
                f"{MIN_DAY_BOUNDARY_MINUTES} and {MAX_DAY_BOUNDARY_MINUTES}"
            )

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.time_zone)

    @property
    def boundary_label(self) -> str:
        hours, minutes = divmod(self.day_boundary_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"


def analytical_day(instant: datetime, config: AnalyticalTime) -> date:
    """Assign an aware instant to its person-local physiological day."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("analytical timestamps must be timezone-aware")
    local = instant.astimezone(config.zone)
    return (local - timedelta(minutes=config.day_boundary_minutes)).date()


def sleep_day(wake_at: datetime, config: AnalyticalTime) -> date:
    """Assign a sleep session to the analytical day containing its wake time."""
    return analytical_day(wake_at, config)


def analytical_day_bounds(day: date, config: AnalyticalTime) -> tuple[datetime, datetime]:
    """Return UTC bounds for one local analytical day, preserving DST length.

    Construction happens as two local wall-clock boundaries on adjacent civil
    dates, then each is converted to UTC. Adding 24 hours to the first UTC bound
    would be wrong on 23/25-hour daylight-saving transition days.
    """
    hours, minutes = divmod(config.day_boundary_minutes, 60)
    boundary = time(hour=hours, minute=minutes, tzinfo=config.zone)
    local_start = datetime.combine(day, boundary)
    local_end = datetime.combine(day + timedelta(days=1), boundary)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)
