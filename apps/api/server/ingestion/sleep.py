"""Backwards-compat shim — sleep ingest now lives in ``storage.timescale.measurements``.

Phase 5E lifted ``ingest_sleep``, ``sleep_session_rows``,
``sleep_stage_segments``, ``_upsert_sleep_session`` and
``_upsert_sleep_stages`` into the storage zone. Callers that reached
``server.ingestion.sleep`` keep working through these re-exports.
"""

from __future__ import annotations

from storage.timescale.measurements import (
    _upsert_sleep_session,
    _upsert_sleep_stages,
    ingest_sleep,
    sleep_session_rows,
    sleep_stage_segments,
)

__all__ = [
    "_upsert_sleep_session",
    "_upsert_sleep_stages",
    "ingest_sleep",
    "sleep_session_rows",
    "sleep_stage_segments",
]
