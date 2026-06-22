"""Timescale-backed fusion reconciliation writer.

The pure rules live in :mod:`normalization.fusion`. This module owns the
database side: persist a reversible semantic-key assertion and an audit row.
It deliberately updates only fusion metadata on canonical observations; raw
observation identity and source stream identity remain untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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
DEVICE_LINK_STATUSES = {"proposed", "confirmed", "rejected", "expired"}


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


@dataclass(frozen=True, slots=True)
class SessionCandidatePair:
    provider_subject_id: str
    direct: SessionObservationCandidate
    relayed: SessionObservationCandidate
    device_link: DeviceLinkConfidence


SESSION_METRIC_ID = "workout.session"
BOUNDARY_TOLERANCE_S = 5.0


_SELECT_SESSION_CANDIDATE_PAIRS_SQL = text(
    """
    SELECT
        COALESCE(
            direct.value_json->'summary'->>'provider_subject_id',
            link.evidence->>'provider_subject_id'
        ) AS provider_subject_id,
        direct.id AS direct_observation_id,
        direct.stream_id AS direct_stream_id,
        COALESCE(
            direct.value_json->'summary'->>'vendor_family',
            link.evidence->>'vendor_family'
        ) AS direct_vendor_family,
        COALESCE(
            direct.value_json->'summary'->>'activity_type',
            direct.value_json->>'label'
        ) AS direct_activity_type,
        EXTRACT(EPOCH FROM direct.interval_start) AS direct_start_epoch_s,
        EXTRACT(EPOCH FROM direct.interval_end) AS direct_end_epoch_s,
        COALESCE(
            direct.value_json->'summary'->>'provider_object_id',
            direct.source_record_uid
        ) AS direct_provider_object_id,
        relayed.id AS relayed_observation_id,
        relayed.stream_id AS relayed_stream_id,
        COALESCE(
            relayed.value_json->'summary'->>'vendor_family',
            direct.value_json->'summary'->>'vendor_family',
            link.evidence->>'vendor_family'
        ) AS relayed_vendor_family,
        COALESCE(
            relayed.value_json->'summary'->>'activity_type',
            relayed.value_json->>'label'
        ) AS relayed_activity_type,
        EXTRACT(EPOCH FROM relayed.interval_start) AS relayed_start_epoch_s,
        EXTRACT(EPOCH FROM relayed.interval_end) AS relayed_end_epoch_s,
        COALESCE(
            relayed.value_json->'summary'->>'provider_object_id',
            relayed.source_record_uid
        ) AS relayed_provider_object_id,
        link.confidence AS device_link_confidence
      FROM device_identity_links link
      JOIN canonical_observations direct
        ON direct.owner_id = link.owner_id
       AND direct.stream_id = link.direct_stream_id
      JOIN canonical_observations relayed
        ON relayed.owner_id = link.owner_id
       AND relayed.stream_id = link.relayed_stream_id
     WHERE link.owner_id = CAST(:owner_id AS UUID)
       AND direct.workspace_id = CAST(:workspace_id AS UUID)
       AND relayed.workspace_id = CAST(:workspace_id AS UUID)
       AND link.status = 'confirmed'
       AND link.confidence IN ('medium', 'strong')
       AND (link.valid_to IS NULL OR link.valid_to > now())
       AND direct.status = 'active'
       AND relayed.status = 'active'
       AND direct.metric_id = :metric_id
       AND relayed.metric_id = :metric_id
       AND direct.aggregation_scope = 'interval_component'
       AND relayed.aggregation_scope = 'interval_component'
       AND direct.semantic_key IS NULL
       AND relayed.semantic_key IS NULL
       AND direct.stream_id IS NOT NULL
       AND relayed.stream_id IS NOT NULL
       AND ABS(EXTRACT(EPOCH FROM direct.interval_start - relayed.interval_start))
           <= :boundary_tolerance_s
       AND ABS(EXTRACT(EPOCH FROM direct.interval_end - relayed.interval_end))
           <= :boundary_tolerance_s
     ORDER BY direct.interval_start DESC
     LIMIT :limit
    """
)

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

_UPSERT_DEVICE_IDENTITY_LINK_SQL = text(
    """
    INSERT INTO device_identity_links (
        owner_id,
        direct_stream_id,
        relayed_stream_id,
        status,
        confidence,
        evidence,
        valid_from,
        valid_to
    ) VALUES (
        CAST(:owner_id AS UUID),
        CAST(:direct_stream_id AS UUID),
        CAST(:relayed_stream_id AS UUID),
        :status,
        :confidence,
        CAST(:evidence AS JSONB),
        COALESCE(CAST(:valid_from AS TIMESTAMPTZ), now()),
        CAST(:valid_to AS TIMESTAMPTZ)
    )
    ON CONFLICT (owner_id, direct_stream_id, relayed_stream_id)
    DO UPDATE SET
        status = EXCLUDED.status,
        confidence = EXCLUDED.confidence,
        evidence = EXCLUDED.evidence,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to
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

    async def upsert_device_identity_link(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        direct_stream_id: UUID,
        relayed_stream_id: UUID,
        status: str,
        confidence: DeviceLinkConfidence,
        evidence: dict[str, object],
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> None:
        """Record a directional direct-vendor -> relayed-stream identity link."""

        if direct_stream_id == relayed_stream_id:
            raise ValueError("device identity link requires two distinct streams")
        if status not in DEVICE_LINK_STATUSES:
            raise ValueError(f"invalid device identity link status: {status}")
        await session.execute(
            _UPSERT_DEVICE_IDENTITY_LINK_SQL,
            {
                "owner_id": str(owner_id),
                "direct_stream_id": str(direct_stream_id),
                "relayed_stream_id": str(relayed_stream_id),
                "status": status,
                "confidence": confidence.value,
                "evidence": json.dumps(evidence, sort_keys=True),
                "valid_from": valid_from.isoformat() if valid_from else None,
                "valid_to": valid_to.isoformat() if valid_to else None,
            },
        )

    async def find_session_candidate_pairs(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        limit: int = 100,
    ) -> list[SessionCandidatePair]:
        result = await session.execute(
            _SELECT_SESSION_CANDIDATE_PAIRS_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "metric_id": SESSION_METRIC_ID,
                "boundary_tolerance_s": BOUNDARY_TOLERANCE_S,
                "limit": limit,
            },
        )
        pairs: list[SessionCandidatePair] = []
        for row in result.mappings().all():
            pair = _row_to_session_candidate_pair(dict(row))
            if pair is not None:
                pairs.append(pair)
        return pairs

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


def _as_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _row_to_session_candidate_pair(row: dict) -> SessionCandidatePair | None:
    provider_subject_id = row.get("provider_subject_id")
    direct_provider_object_id = row.get("direct_provider_object_id")
    if not provider_subject_id or not direct_provider_object_id:
        return None

    direct_vendor_family = row.get("direct_vendor_family")
    relayed_vendor_family = row.get("relayed_vendor_family")
    direct_activity_type = row.get("direct_activity_type")
    relayed_activity_type = row.get("relayed_activity_type")
    if not (
        direct_vendor_family
        and relayed_vendor_family
        and direct_activity_type
        and relayed_activity_type
    ):
        return None

    try:
        device_link = DeviceLinkConfidence(str(row["device_link_confidence"]))
    except (KeyError, ValueError):
        return None

    direct = SessionObservationCandidate(
        observation_id=_as_uuid(row["direct_observation_id"]),
        stream_id=_as_uuid(row["direct_stream_id"]),
        vendor_family=str(direct_vendor_family),
        activity_type=str(direct_activity_type),
        start_epoch_s=float(row["direct_start_epoch_s"]),
        end_epoch_s=float(row["direct_end_epoch_s"]),
        provider_object_id=str(direct_provider_object_id),
        variant_tier=VariantTier.DIRECT_WITH_PROVIDER_ID,
    )
    relayed = SessionObservationCandidate(
        observation_id=_as_uuid(row["relayed_observation_id"]),
        stream_id=_as_uuid(row["relayed_stream_id"]),
        vendor_family=str(relayed_vendor_family),
        activity_type=str(relayed_activity_type),
        start_epoch_s=float(row["relayed_start_epoch_s"]),
        end_epoch_s=float(row["relayed_end_epoch_s"]),
        provider_object_id=str(row["relayed_provider_object_id"])
        if row.get("relayed_provider_object_id")
        else None,
        variant_tier=VariantTier.HC_PACKAGE_AND_DEVICE,
    )
    return SessionCandidatePair(
        provider_subject_id=str(provider_subject_id),
        direct=direct,
        relayed=relayed,
        device_link=device_link,
    )
