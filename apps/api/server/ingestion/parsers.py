"""Re-export shim — parsers moved to ``normalization.parsers`` (ARCH-001).

The pure sample parsers now live below the storage layer so storage writers can
import them without an upward dependency on the API package. The API layer,
plugins, and tests keep importing ``server.ingestion.parsers`` via these
re-exports; the canonical home is ``normalization.parsers``.
"""

from normalization.parsers import (
    duration_ms_between,
    first_present,
    group_samples_by_device,
    normalize_blood_oxygen,
    parse_date,
    parse_ts,
    sample_device_name,
    to_float,
    to_int,
)

__all__ = [
    "duration_ms_between",
    "first_present",
    "group_samples_by_device",
    "normalize_blood_oxygen",
    "parse_date",
    "parse_ts",
    "sample_device_name",
    "to_float",
    "to_int",
]
