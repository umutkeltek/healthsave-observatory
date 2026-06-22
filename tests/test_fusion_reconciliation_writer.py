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
from storage.timescale import fusion as fusion_module
from storage.timescale.fusion import (
    FusionReconciliationRepository,
    SessionCandidatePair,
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
    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict]:
        return []


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _FakeResult()


class _FakeRowsResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _FakeRowsResult:
        return self

    def all(self) -> list[dict]:
        return self._rows


class _FakeRowsSession:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple[str, object]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _FakeRowsResult(self.rows)


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


@pytest.mark.asyncio
async def test_find_session_candidate_pairs_uses_confirmed_device_links() -> None:
    repo = FusionReconciliationRepository()
    row = {
        "provider_subject_id": "polar-user-10579",
        "direct_observation_id": DIRECT_OBS,
        "direct_stream_id": DIRECT_STREAM,
        "direct_vendor_family": "polar",
        "direct_activity_type": "RUNNING",
        "direct_start_epoch_s": T0.timestamp(),
        "direct_end_epoch_s": T1.timestamp(),
        "direct_provider_object_id": "polar-exercise-1",
        "relayed_observation_id": RELAYED_OBS,
        "relayed_stream_id": RELAYED_STREAM,
        "relayed_vendor_family": "polar",
        "relayed_activity_type": "RUNNING",
        "relayed_start_epoch_s": T0.timestamp(),
        "relayed_end_epoch_s": T1.timestamp(),
        "relayed_provider_object_id": None,
        "device_link_confidence": "strong",
    }
    session = _FakeRowsSession([row])

    pairs = await repo.find_session_candidate_pairs(
        session,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        limit=25,
    )

    assert len(pairs) == 1
    pair = pairs[0]
    assert isinstance(pair, SessionCandidatePair)
    assert pair.provider_subject_id == "polar-user-10579"
    assert pair.device_link == DeviceLinkConfidence.STRONG
    assert pair.direct.provider_object_id == "polar-exercise-1"
    assert pair.relayed.provider_object_id is None
    assert pair.direct.variant_tier == VariantTier.DIRECT_WITH_PROVIDER_ID
    assert pair.relayed.variant_tier == VariantTier.HC_PACKAGE_AND_DEVICE

    sql, params = session.calls[0]
    assert "device_identity_links" in sql
    assert "link.status = 'confirmed'" in sql
    assert "workout.session" not in sql
    assert params["metric_id"] == "workout.session"
    assert params["owner_id"] == str(OWNER)
    assert params["workspace_id"] == str(WORKSPACE)
    assert params["limit"] == 25


@pytest.mark.asyncio
async def test_find_session_candidate_pairs_skips_rows_without_provider_anchor() -> None:
    repo = FusionReconciliationRepository()
    session = _FakeRowsSession(
        [
            {
                "provider_subject_id": "polar-user-10579",
                "direct_observation_id": DIRECT_OBS,
                "direct_stream_id": DIRECT_STREAM,
                "direct_vendor_family": "polar",
                "direct_activity_type": "RUNNING",
                "direct_start_epoch_s": T0.timestamp(),
                "direct_end_epoch_s": T1.timestamp(),
                "direct_provider_object_id": None,
                "relayed_observation_id": RELAYED_OBS,
                "relayed_stream_id": RELAYED_STREAM,
                "relayed_vendor_family": "polar",
                "relayed_activity_type": "RUNNING",
                "relayed_start_epoch_s": T0.timestamp(),
                "relayed_end_epoch_s": T1.timestamp(),
                "relayed_provider_object_id": None,
                "device_link_confidence": "strong",
            }
        ]
    )

    assert (
        await repo.find_session_candidate_pairs(
            session,
            owner_id=OWNER,
            workspace_id=WORKSPACE,
        )
        == []
    )


def test_candidate_pair_sql_uses_executable_confirmed_device_link_filters() -> None:
    sql = str(fusion_module._SELECT_SESSION_CANDIDATE_PAIRS_SQL)

    assert ") AS direct_vendor_family" in sql
    assert ") AS direct_activity_type" in sql
    assert ") AS relayed_vendor_family" in sql
    assert ") AS relayed_activity_type" in sql
    assert "EXTRACT(EPOCH FROM direct.interval_start) AS direct_start_epoch_s" in sql
    assert "EXTRACT(EPOCH FROM relayed.interval_end) AS relayed_end_epoch_s" in sql
    assert "link.status = 'confirmed'" in sql
    assert "link.confidence IN ('medium', 'strong')" in sql
    assert "AND direct.semantic_key IS NULL" in sql
    assert "AND relayed.semantic_key IS NULL" in sql
    assert "AND direct.stream_id IS NOT NULL" in sql
    assert "AND relayed.stream_id IS NOT NULL" in sql


def test_variant_update_sql_has_where_clause_and_case_assignment() -> None:
    sql = str(fusion_module._UPDATE_VARIANTS_SQL)

    assert "is_primary = CASE WHEN" in sql
    assert "WHERE owner_id = CAST(:owner_id AS UUID)" in sql
    assert "AND id = ANY(CAST(:variant_ids AS UUID[]))" in sql


@pytest.mark.asyncio
async def test_upsert_device_identity_link_records_directional_confirmed_link() -> None:
    repo = FusionReconciliationRepository()
    session = _FakeSession()

    await repo.upsert_device_identity_link(
        session,
        owner_id=OWNER,
        direct_stream_id=DIRECT_STREAM,
        relayed_stream_id=RELAYED_STREAM,
        status="confirmed",
        confidence=DeviceLinkConfidence.STRONG,
        evidence={
            "vendor_family": "polar",
            "provider_subject_id": "polar-user-10579",
            "reason": "operator confirmed same physical device",
        },
    )

    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "INSERT INTO device_identity_links" in sql
    assert "ON CONFLICT (owner_id, direct_stream_id, relayed_stream_id)" in sql
    assert params["owner_id"] == str(OWNER)
    assert params["direct_stream_id"] == str(DIRECT_STREAM)
    assert params["relayed_stream_id"] == str(RELAYED_STREAM)
    assert params["status"] == "confirmed"
    assert params["confidence"] == "strong"
    assert "operator confirmed" in params["evidence"]
