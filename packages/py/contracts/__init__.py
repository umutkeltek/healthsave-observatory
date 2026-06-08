# SPDX-License-Identifier: Apache-2.0
"""v2 canonical contracts.

The single source of truth for v2 wire shapes — Pydantic in Python,
generated everywhere else (JSON Schema via ``make regen-v2-schemas``,
TS types via the codegen pipeline once it lands).

Imports from here are v2 by definition. Imports from ``compat_v1``
are v1-frozen by definition. The two never cross-reference (enforced
by ``tests/contract/v2/test_v2_invariants.py::test_contracts_never_imports_compat_v1``).

Re-exported for ergonomic ``from contracts import X``. Subpackage
imports (``from contracts.data import Measurement``) work too.
"""

from __future__ import annotations

from ._base import (
    DEFAULT_OWNER_ID,
    DEFAULT_WORKSPACE_ID,
    ArtifactId,
    DecisionId,
    DeviceId,
    EventId,
    ExecutionId,
    MeasurementId,
    OwnerId,
    ProposalId,
    Provenance,
    RunId,
    SourceId,
    V2Model,
    WithOwnership,
    WorkspaceId,
)
from .agents import (
    ActionDecision,
    ActionExecution,
    ActionProposal,
    AgentArtifact,
    AgentEvent,
    AgentRun,
    AgentSpec,
    Observation,
)
from .data import (
    Device,
    IngestionError,
    IngestionRun,
    Measurement,
    NormalizedMeasurement,
    RawSourcePayload,
    Source,
    SourceCapability,
)
from .narrative import (
    Claim,
    EvidenceRef,
    Insight,
    NarrativeArtifact,
    SuggestedAction,
    Uncertainty,
)
from .plugins import PluginCapability, PluginManifest, PluginPermissions
from .ui import Annotation, ChartSpec, NarrativeCard, SeriesResponse

# Single canonical list of every public type — drives the schema
# export script and the test that asserts every public type is
# JSON-Schema-serializable.
ALL_MODELS: tuple[type[V2Model], ...] = (
    # base
    Provenance,
    # data
    Source,
    Device,
    RawSourcePayload,
    NormalizedMeasurement,
    Measurement,
    SourceCapability,
    IngestionRun,
    IngestionError,
    # agents
    AgentSpec,
    AgentRun,
    Observation,
    ActionProposal,
    ActionDecision,
    ActionExecution,
    AgentEvent,
    AgentArtifact,
    # narrative
    EvidenceRef,
    Uncertainty,
    Claim,
    Insight,
    SuggestedAction,
    NarrativeArtifact,
    # ui
    Annotation,
    SeriesResponse,
    ChartSpec,
    NarrativeCard,
    # plugins
    PluginCapability,
    PluginPermissions,
    PluginManifest,
)

__all__ = [
    # base
    "DEFAULT_OWNER_ID",
    "DEFAULT_WORKSPACE_ID",
    "OwnerId",
    "WorkspaceId",
    "SourceId",
    "DeviceId",
    "RunId",
    "EventId",
    "ProposalId",
    "DecisionId",
    "ExecutionId",
    "ArtifactId",
    "MeasurementId",
    "Provenance",
    "V2Model",
    "WithOwnership",
    "ALL_MODELS",
    # data
    "Source",
    "Device",
    "RawSourcePayload",
    "NormalizedMeasurement",
    "Measurement",
    "SourceCapability",
    "IngestionRun",
    "IngestionError",
    # agents
    "AgentSpec",
    "AgentRun",
    "Observation",
    "ActionProposal",
    "ActionDecision",
    "ActionExecution",
    "AgentEvent",
    "AgentArtifact",
    # narrative
    "EvidenceRef",
    "Uncertainty",
    "Claim",
    "Insight",
    "SuggestedAction",
    "NarrativeArtifact",
    # ui
    "Annotation",
    "SeriesResponse",
    "ChartSpec",
    "NarrativeCard",
    # plugins
    "PluginCapability",
    "PluginPermissions",
    "PluginManifest",
]
