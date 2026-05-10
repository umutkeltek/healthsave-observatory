"""Backwards-compat shim — SQL now lives in ``storage.timescale.measurements``.

Phase 5E lifted every per-metric writer plus the device + raw-payload
audit-log functions out of this module into the storage zone. The
re-exports below preserve the historical names so registry, route,
and tests keep working without import-path churn.

The shim disappears once the last caller migrates (or in a future
dedicated 'delete the shims' phase).
"""

from __future__ import annotations

from storage.timescale.measurements import (
    _get_or_create_device,
    _ingest_activity,
    _ingest_daily_quantity,
    _ingest_dedicated,
    _ingest_generic,
    _ingest_metric,
    _ingest_sleep,
    _ingest_workouts,
    _log_raw_ingestion,
    _mark_raw_ingestion_processed,
)

__all__ = [
    "_get_or_create_device",
    "_ingest_activity",
    "_ingest_daily_quantity",
    "_ingest_dedicated",
    "_ingest_generic",
    "_ingest_metric",
    "_ingest_sleep",
    "_ingest_workouts",
    "_log_raw_ingestion",
    "_mark_raw_ingestion_processed",
]
