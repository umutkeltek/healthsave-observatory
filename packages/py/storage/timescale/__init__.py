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

Eager-import policy: only modules that have NO cross-package imports
are eager-loaded here. ``measurements`` reaches into
``server.ingestion`` helpers (mappers/parsers/owner) and ``analysis``
loads on demand from analysis-package call sites that we cannot
afford to pre-load before ``server`` exists. Both stay submodule-only
(``from storage.timescale.{measurements,analysis} import ...``) until
the helpers move out of ``server.ingestion`` or the ``handlers`` shim
retires (handoff #2 / #4).
"""

from . import briefings, ingest, runs
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
from .runs import (
    PipelineRun,
    PipelineStatus,
    TimescaleRunRepository,
    TriggeredBy,
)

__all__ = [
    # modules — preferred for module-level convenience calls
    "briefings",
    "ingest",
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
    # `measurements` and `analysis` are submodule-only (see policy
    # note above): import them as
    #   from storage.timescale.measurements import ...
    #   from storage.timescale.analysis import ...
]
