"""Timescale-backed fusion reconciliation writer.

The pure rules live in :mod:`normalization.fusion`. This module owns the
database side: persist a reversible semantic-key assertion and an audit row.
It deliberately updates only fusion metadata on canonical observations; raw
observation identity and source stream identity remain untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from normalization.fusion import (
    DeviceLinkConfidence,
    SessionCandidate,
    VariantTier,
    decide_session_fusion,
    select_primary,
    semantic_key,
)
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SEMANTIC_KEY_VERSION = "matcher:session:v1"
MATCHER_ID = "session"
MATCHER_VERSION = "v1"
OBJECT_TYPE_EXERCISE = "exercise"


@dataclass(frozen=True, slots=True)
class SessionObservationCandidate:
    """Canonical observation row projected into the pure fusion candidate shape."""

    observation_id: UUID
    stream_id: UUID
    vendor_family: str
    activity_type: str
    start_epoch_s: float
    end_epoch_s: float
    provider_object_id: str | None
    variant_tier: VariantTier

    def to_session_candidate(self) -> SessionCandidate:
        return SessionCandidate(
            vendor_family=self.vendor_family,
            activity_type=self.activity_type,
            start_epoch_s=self.start_epoch_s,
            end_epoch_s=self.end_epoch_s,
            provider_object_id=self.provider_object_id,
        )


@dataclass(frozen=True, slots=True)
class FusionReconciliationResult:
    assigned: bool
    semantic_key: str
    reason: str
    primary_observation_id: UUID | None
    variant_observation_ids: tuple[UUID, ...]


_UPDATE_VARIANTS_SQL = text(
    """
    UPDATE canonical_observations
       SET semantic_key = :semantic_key,
           semantic_key_version = :semantic_key_version,
           aggregation_scope = 'interval_component',
           is_primary = CASE WHEN id = CAST(:primary_id AS UUID) THEN TRUE ELSE FALSE END
     WHERE owner_id = CAST(:owner_id AS UUID)
       AND workspace_id = CAST(:workspace_id AS UUID)
       AND id = ANY(CAST(:variant_ids AS UUID[]))
    """
)

_INSERT_DECISION_SQL = text(
    """
    INSERT INTO fusion_decisions (
        owner_id,
        workspace_id,
        semantic_key,
        semantic_key_version,
        matcher_id,
        matcher_version,
        decision,
        confidence,
        primary_observation_id,
        variant_observation_ids,
        decided_by,
        evidence
    ) VALUES (
        CAST(:owner_id AS UUID),
        CAST(:workspace_id AS UUID),
        :semantic_key,
        :semantic_key_version,
        :matcher_id,
        :matcher_version,
        :decision,
        :confidence,
        CAST(:primary_observation_id AS UUID),
        CAST(:variant_observation_ids AS UUID[]),
        :decided_by,
        CAST(:evidence AS JSONB)
    )
    """
)


class FusionReconciliationRepository:
    """Persist session-level fusion decisions for canonical observations."""

    async def reconcile_session_pair(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        provider_subject_id: str,
        direct: SessionObservationCandidate,
        relayed: SessionObservationCandidate,
        device_link: DeviceLinkConfidence,
        decided_by: str = "system",
    ) -> FusionReconciliationResult:
        sem_key = semantic_key(
            direct.vendor_family,
            provider_subject_id,
            OBJECT_TYPE_EXERCISE,
            direct.provider_object_id,
        )
        if sem_key is None:
            raise ValueError("direct candidate requires provider_subject_id and provider_object_id")

        decision = decide_session_fusion(
            direct.to_session_candidate(),
            relayed.to_session_candidate(),
            device_link,
        )
        variant_ids = (direct.observation_id, relayed.observation_id)
        primary_id: UUID | None = None
        confidence = 0.0

        if decision.fuse:
            primary_index = select_primary([direct.variant_tier, relayed.variant_tier])
            if primary_index is None:
                raise ValueError("fusion assignment requires at least one variant")
            primary_id = variant_ids[primary_index]
            confidence = 1.0
            await self._assign_variants(
                session,
                owner_id=owner_id,
                workspace_id=workspace_id,
                semantic_key=sem_key,
                primary_observation_id=primary_id,
                variant_observation_ids=variant_ids,
            )

        await self._record_decision(
            session,
            owner_id=owner_id,
            workspace_id=workspace_id,
            semantic_key=sem_key,
            decision="assigned" if decision.fuse else "rejected",
            confidence=confidence,
            primary_observation_id=primary_id,
            variant_observation_ids=variant_ids,
            decided_by=decided_by,
            evidence={
                "reason": decision.reason,
                "direct_observation_id": str(direct.observation_id),
                "relayed_observation_id": str(relayed.observation_id),
                "direct_stream_id": str(direct.stream_id),
                "relayed_stream_id": str(relayed.stream_id),
                "device_link_confidence": device_link.value,
            },
        )

        return FusionReconciliationResult(
            assigned=decision.fuse,
            semantic_key=sem_key,
            reason=decision.reason,
            primary_observation_id=primary_id,
            variant_observation_ids=variant_ids,
        )

    async def _assign_variants(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        semantic_key: str,
        primary_observation_id: UUID,
        variant_observation_ids: tuple[UUID, ...],
    ) -> None:
        await session.execute(
            _UPDATE_VARIANTS_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "semantic_key": semantic_key,
                "semantic_key_version": SEMANTIC_KEY_VERSION,
                "primary_id": str(primary_observation_id),
                "variant_ids": [str(item) for item in variant_observation_ids],
            },
        )

    async def _record_decision(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        semantic_key: str,
        decision: str,
        confidence: float,
        primary_observation_id: UUID | None,
        variant_observation_ids: tuple[UUID, ...],
        decided_by: str,
        evidence: dict[str, str],
    ) -> None:
        await session.execute(
            _INSERT_DECISION_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "semantic_key": semantic_key,
                "semantic_key_version": SEMANTIC_KEY_VERSION,
                "matcher_id": MATCHER_ID,
                "matcher_version": MATCHER_VERSION,
                "decision": decision,
                "confidence": confidence,
                "primary_observation_id": str(primary_observation_id)
                if primary_observation_id
                else None,
                "variant_observation_ids": [str(item) for item in variant_observation_ids],
                "decided_by": decided_by,
                "evidence": json.dumps(evidence, sort_keys=True),
            },
        )


default_repository = FusionReconciliationRepository()
