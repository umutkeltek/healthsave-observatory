# SPDX-License-Identifier: Apache-2.0
"""Foundation types shared by every v2 contract.

- Identifier aliases — `OwnerId`, `WorkspaceId`, etc. — are UUIDs but
  named for intent. The intent is what the type system protects.
- ``DEFAULT_OWNER_ID`` / ``DEFAULT_WORKSPACE_ID`` match the v1 sentinel
  in ``compat_v1`` and ``server.ingestion.owner`` so a self-hosted
  single-user install Just Works without coordinating an upgrade.
- ``V2Model`` is the base class. ``extra="forbid"`` means an unknown
  field at validation time fails loudly — desirable for canonical
  contracts where silent acceptance hides drift.
- ``WithOwnership`` carries ``owner_id`` + ``workspace_id`` on every
  record that represents user data. Plugin manifest and similar
  process-level types do NOT extend this — they are not user data.
- ``Provenance`` is the always-attached "where did this come from"
  capsule for every measurement / artifact / event.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Identifier aliases — semantic types over bare UUID for grep-ability.
OwnerId = UUID
WorkspaceId = UUID
SourceId = UUID
DeviceId = UUID
RunId = UUID
EventId = UUID
ProposalId = UUID
DecisionId = UUID
ExecutionId = UUID
ArtifactId = UUID
MeasurementId = UUID

# Single-user / single-workspace v1 sentinels. Mirrors the values used
# at ``compat_v1`` and ``server/ingestion/owner.py`` so a self-hosted
# install with no header serves traffic under one stable identity.
DEFAULT_OWNER_ID: OwnerId = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_WORKSPACE_ID: WorkspaceId = UUID("00000000-0000-0000-0000-000000000001")


class V2Model(BaseModel):
    """Base for every v2 contract type.

    ``extra='forbid'`` rejects unknown fields at validation time —
    canonical contracts don't quietly accept drift; the wire is
    explicit or it fails loudly.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )


class WithOwnership(V2Model):
    """Mixin: every record that represents user data carries an
    owner + workspace tuple. Multi-user / family / federated setups
    later become a matter of populating different ids; the schema
    is already shaped for it.
    """

    owner_id: OwnerId = Field(default=DEFAULT_OWNER_ID)
    workspace_id: WorkspaceId = Field(default=DEFAULT_WORKSPACE_ID)


class Provenance(V2Model):
    """Always-attached "where did this come from" capsule.

    ``raw_payload_ref`` is opaque — typically a row id in
    ``raw_ingestion_log`` so a future replay can reach the exact
    bytes. Storage detail intentionally lives on the other side of
    the storage port.
    """

    source_plugin_id: str
    sdk_version: str
    captured_at: datetime
    raw_payload_ref: str | None = None
