"""Datahub agent supervisor — Phase 7-C.

Slim always-on Python process that loads enabled :class:`plugin_sdk.Agent`
plugins, ticks each at its configured interval, wraps every plugin call
in :func:`plugin_sdk.error_boundary` + :func:`plugin_sdk.with_deadline`,
and persists typed proposals through :class:`storage.ports.AgentRepository`.

Phase 7-C ships the supervisor seam only. The anomaly-watcher plugin and
its concrete observation feed land in Phase 7-D against the generic
:class:`agents.supervisor.ObservationFeed` Protocol.
"""

from .config import (
    AgentsConfig,
    AgentsDefaults,
    AgentSettings,
    UnknownAgentError,
    load_agents_config,
)
from .supervisor import (
    AGENT_RUNTIME_FAILURES,
    EnabledAgent,
    Observation,
    ObservationFeed,
    Supervisor,
)

# Note: ``UnknownObservationFeedError`` lives in :mod:`agents.main` and
# is NOT re-exported here — pulling :mod:`agents.main` into every
# ``import agents`` would drag :mod:`server.db.session` (the engine
# bootstrap) into test paths that don't need it. Import it directly
# from :mod:`agents.main` if you need it.

__all__ = [
    "AgentsConfig",
    "AgentsDefaults",
    "AgentSettings",
    "UnknownAgentError",
    "load_agents_config",
    "AGENT_RUNTIME_FAILURES",
    "EnabledAgent",
    "Observation",
    "ObservationFeed",
    "Supervisor",
]
