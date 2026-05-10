"""TimescaleDB-backed measurement repository — placeholder for Phase 5D.

Defines the class shape so consumers can begin importing from
``storage.timescale.measurements`` and we can add concrete methods
incrementally as the per-metric SQL migrates out of
``server.ingestion.handlers``.

Phase 5C ships the Protocol + skeleton class. Phase 5D fills in
methods (insert_heart_rate, insert_workout, fetch_series, etc.) and
removes the corresponding raw SQL from ``handlers.py``.
"""

from __future__ import annotations


class TimescaleMeasurementRepository:
    """TimescaleDB :class:`storage.ports.MeasurementRepository`.

    Methods land here in Phase 5D as the handler-level SQL migrates
    over. Today this class is intentionally empty — the Protocol
    contract has zero required methods (also Phase 5D), so an empty
    implementation already satisfies it.
    """


default_repository = TimescaleMeasurementRepository()
