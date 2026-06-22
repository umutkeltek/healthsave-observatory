"""Acceptance guard for direct-vendor + relayed Health Connect fusion.

This does not add a reconciler yet. It pins the architecture we just built:
the fusion core decides conservatively, the semantic key is provider-rooted,
direct rows win as primary, raw rows stay distinct, and fused reads collapse
only by persisted fusion metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from normalization.fusion import (
    DeviceLinkConfidence,
    SessionCandidate,
    VariantTier,
    decide_session_fusion,
    select_primary,
    semantic_key,
)
from storage.timescale.observations import CanonicalObservationRepository

OWNER = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE = UUID("00000000-0000-0000-0000-000000000001")
POLAR_SOURCE = UUID("11111111-1111-4111-8111-111111111111")
HC_SOURCE = UUID("22222222-2222-4222-8222-222222222222")
T0 = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple] = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _FakeResult(self.rows)


def _series_row(
    *,
    source_id: UUID,
    stream_id: str,
    semantic: str,
    is_primary: bool,
) -> dict:
    return {
        "interval_start": T0,
        "interval_end": T1,
        "numeric_value": 1800.0,
        "code": None,
        "canonical_unit": "s",
        "source_id": source_id,
        "stream_id": stream_id,
        "confidence": None,
        "semantic_key": semantic,
        "aggregation_scope": "interval_component",
        "is_primary": is_primary,
    }


@pytest.mark.asyncio
async def test_direct_polar_and_relayed_health_connect_workout_fuse_at_read_time_only():
    direct = SessionCandidate(
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=T0.timestamp(),
        end_epoch_s=T1.timestamp(),
        provider_object_id="polar-exercise-1",
    )
    relayed = SessionCandidate(
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=T0.timestamp() + 2,
        end_epoch_s=T1.timestamp() + 1,
        provider_object_id=None,
    )

    decision = decide_session_fusion(direct, relayed, DeviceLinkConfidence.STRONG)
    assert decision.fuse is True

    sem_key = semantic_key(
        "polar",
        "polar-user-10579",
        "exercise",
        direct.provider_object_id,
    )
    assert sem_key == "sem:v1:polar:polar-user-10579:exercise:polar-exercise-1"

    primary_index = select_primary(
        [VariantTier.DIRECT_WITH_PROVIDER_ID, VariantTier.HC_PACKAGE_AND_DEVICE]
    )
    assert primary_index == 0

    direct_row = _series_row(
        source_id=POLAR_SOURCE,
        stream_id="polar-direct-stream",
        semantic=sem_key,
        is_primary=True,
    )
    relayed_row = _series_row(
        source_id=HC_SOURCE,
        stream_id="health-connect-relayed-stream",
        semantic=sem_key,
        is_primary=False,
    )

    repo = CanonicalObservationRepository()
    raw_session = _FakeSession([direct_row, relayed_row])
    raw_points = await repo.query_series(
        raw_session,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        metric_id="exercise_duration_seconds",
        start=T0,
        end=T1,
    )

    fused_session = _FakeSession([direct_row])
    fused_points = await repo.query_fused_series(
        fused_session,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        metric_id="exercise_duration_seconds",
        start=T0,
        end=T1,
    )

    assert {point.stream_id for point in raw_points} == {
        "polar-direct-stream",
        "health-connect-relayed-stream",
    }
    assert len(fused_points) == 1
    assert fused_points[0].stream_id == "polar-direct-stream"
    assert fused_points[0].semantic_key == sem_key
    assert fused_points[0].is_primary is True
