"""Re-export shim — metric→table mapping moved to ``normalization.mappers`` (ARCH-001).

The mapping config drives the storage writers, so it now lives below the storage
layer (no upward import from storage). The API layer, plugins, and tests keep
importing ``server.ingestion.mappers`` via these re-exports; the canonical home
is ``normalization.mappers``.
"""

from normalization.mappers import (
    ACTIVITY_FIELDS,
    DAILY_ACTIVITY_QUANTITY_FIELDS,
    DEDICATED_TABLES,
)

__all__ = [
    "ACTIVITY_FIELDS",
    "DAILY_ACTIVITY_QUANTITY_FIELDS",
    "DEDICATED_TABLES",
]
