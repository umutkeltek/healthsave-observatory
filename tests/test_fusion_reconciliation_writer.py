"""Timescale fusion reconciliation writer.

The pure fusion core decides if two sessions may fuse. This storage module is
responsible for making that decision durable without mutating raw observation
identity: write semantic metadata to the variants and append an audit row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_DNS, UUID, uuid5

import pytest

from normalization.fusion import DeviceLinkConfidence, VariantTier
from storage.timescale.fusion import (
    FusionReconciliationRepository,
    SessionObservationCandidate,
)

OWNER = uuid5(NAMESPACE_DNS, "healthsave.test.owner")
WORKSPACE = uuid5(NAMESPACE_DNS, "healthsave.test.workspace")
DIRECT_OBS = uuid5(NAMESPACE_DNS, "healthsave.test.obs.direct-polar")
RELAYED_OBS = uuid5(NAMESPACE_DNS, "healthsave.test.obs.relayed-health-connect")
DIRECT_STREAM = uuid5(NAMESPACE_DNS, "healthsave.test.stream.direct-polar")
RELAYED_STREAM = uuid5(NAMESPACE_DNS, "healthsave.test.stream.relayed-health-connect")
T0 = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)


class _FakeResult:
    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return []


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _FakeResult()


def _candidate(
    *,
    observation_id: UUID,
    stream_id: UUID,
    provider_object_id: str | None,
    tier: VariantTier,
) -> SessionObservationCandidate:
    return SessionObservationCandidate(
        observation_id=observation_id,
        stream_id=stream_id,
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=T0.timestamp(),
        end_epoch_s=T1.timestamp(),
        provider_object_id=provider_object_id,
        variant_tier=tier,
    )


@pytest.mark.asyncio
async def test_reconcile_session_pair_assigns_semantic_key_and_audit_row() -> None:
    repo = FusionReconciliationRepository()
    session = _FakeSession()
    direct = _candidate(
        observation_id=DIRECT_OBS,
        stream_id=DIRECT_STREAM,
        provider_object_id="polar-exercise-1",
        tier=VariantTier.DIRECT_WITH_PROVIDER_ID,
    )
    relayed = _candidate(
        observation_id=RELAYED_OBS,
        stream_id=RELAYED_STREAM,
        provider_object_id=None,
        tier=VariantTier.HC_PACKAGE_AND_DEVICE,
    )

    result = await repo.reconcile_session_pair(
        session,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        provider_subject_id="polar-user-10579",
        direct=direct,
        relayed=relayed,
        device_link=DeviceLinkConfidence.STRONG,
    )

    assert result.assigned is True
    assert result.primary_observation_id == DIRECT_OBS
    assert result.semantic_key == "sem:v1:polar:polar-user-10579:exercise:polar-exercise-1"

    assert len(session.calls) == 2
    update_sql, update_params = session.calls[0]
    insert_sql, insert_params = session.calls[1]

    assert "UPDATE canonical_observations" in update_sql
    assert update_params["semantic_key"] == result.semantic_key
    assert update_params["primary_id"] == str(DIRECT_OBS)
    assert update_params["variant_ids"] == [str(DIRECT_OBS), str(RELAYED_OBS)]

    assert "INSERT INTO fusion_decisions" in insert_sql
    assert insert_params["decision"] == "assigned"
    assert insert_params["primary_observation_id"] == str(DIRECT_OBS)
    assert insert_params["variant_observation_ids"] == [str(DIRECT_OBS), str(RELAYED_OBS)]
    assert insert_params["confidence"] == 1.0
    assert "vendor + device-link" in insert_params["evidence"]


@pytest.mark.asyncio
async def test_reconcile_session_pair_rejects_weak_device_link_without_variant_update() -> None:
    repo = FusionReconciliationRepository()
    session = _FakeSession()
    direct = _candidate(
        observation_id=DIRECT_OBS,
        stream_id=DIRECT_STREAM,
        provider_object_id="polar-exercise-1",
        tier=VariantTier.DIRECT_WITH_PROVIDER_ID,
    )
    relayed = _candidate(
        observation_id=RELAYED_OBS,
        stream_id=RELAYED_STREAM,
        provider_object_id=None,
        tier=VariantTier.HC_PACKAGE_AND_DEVICE,
    )

    result = await repo.reconcile_session_pair(
        session,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        provider_subject_id="polar-user-10579",
        direct=direct,
        relayed=relayed,
        device_link=DeviceLinkConfidence.WEAK,
    )

    assert result.assigned is False
    assert result.primary_observation_id is None
    assert result.semantic_key == "sem:v1:polar:polar-user-10579:exercise:polar-exercise-1"

    assert len(session.calls) == 1
    insert_sql, insert_params = session.calls[0]
    assert "INSERT INTO fusion_decisions" in insert_sql
    assert insert_params["decision"] == "rejected"
    assert insert_params["primary_observation_id"] is None
    assert insert_params["variant_observation_ids"] == [str(DIRECT_OBS), str(RELAYED_OBS)]
    assert "device link too weak" in insert_params["evidence"]
