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

from . import briefings, runs
from .briefings import (
    FindingRow,
    NarrativeRow,
    TimescaleBriefingRepository,
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
    "runs",
    # runs — public types
    "PipelineRun",
    "PipelineStatus",
    "TimescaleRunRepository",
    "TriggeredBy",
    # briefings — public types
    "FindingRow",
    "NarrativeRow",
    "TimescaleBriefingRepository",
]
