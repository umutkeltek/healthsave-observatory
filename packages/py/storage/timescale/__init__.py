"""TimescaleDB implementations of the ports in ``storage.ports``.

The only place sqlalchemy + raw SQL live in the v2 layout (post Phase 5D
cleanup). app code talks to ``storage.ports`` Protocols; this package
provides the concrete behaviour.

Each module typically exposes:
- A class implementing the Protocol (e.g. ``TimescaleRunRepository``).
- A module-level default instance bound to the project's
  ``async_session`` factory.
- Module-level convenience functions delegating to the default
  instance, for backwards compatibility with v1.x callers that pass a
  session directly without injecting a repository.
"""

from . import analysis, briefings, ingest, measurements, runs
from .briefings import (
    FindingRow,
    NarrativeRow,
    TimescaleBriefingRepository,
)
from .ingest import (
    PostgresAuditLog,
    PostgresIngestStorage,
    default_audit_log,
    default_storage,
)
from .measurements import TimescaleMeasurementRepository
from .runs import (
    PipelineRun,
    PipelineStatus,
    TimescaleRunRepository,
    TriggeredBy,
)

__all__ = [
    # modules — preferred for module-level convenience calls
    "analysis",
    "briefings",
    "ingest",
    "measurements",
    "runs",
    # runs
    "PipelineRun",
    "PipelineStatus",
    "TimescaleRunRepository",
    "TriggeredBy",
    # briefings
    "FindingRow",
    "NarrativeRow",
    "TimescaleBriefingRepository",
    # ingest (relocated from server/ingestion/storage.py)
    "PostgresAuditLog",
    "PostgresIngestStorage",
    "default_audit_log",
    "default_storage",
    # measurements (Phase 5C skeleton)
    "TimescaleMeasurementRepository",
]
