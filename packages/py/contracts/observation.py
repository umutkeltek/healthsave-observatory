# SPDX-License-Identifier: Apache-2.0
"""The canonical health observation — the record every v2 normalizer emits.

Device-agnostic: the whole v2 stack keys on ``Observation``, not on per-source
shapes. ``value`` is the tagged union from :mod:`contracts.values`
(quantity / categorical / components / event / waveform / json). Instant samples
set ``interval_start == interval_end``; ranged samples (sleep stage, workout)
set both. Additive to the in-use ``contracts.data.Measurement(value: float)`` —
this is the v2 canonical record that replaces it once the pipeline is migrated.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from ._base import DeviceId, MeasurementId, Provenance, SourceId, WithOwnership
from .ontology import ONTOLOGY_VERSION, MetricId
from .values import ObservationValue


class Observation(WithOwnership):
    """One canonical health observation after a source plugin normalizes a sample."""

    id: MeasurementId = Field(default_factory=uuid4)
    metric_id: MetricId
    ontology_version: str = ONTOLOGY_VERSION
    value: ObservationValue
    interval_start: datetime
    interval_end: datetime
    recorded_at: datetime | None = None
    source_id: SourceId
    device_id: DeviceId | None = None
    stream_id: UUID | None = None
    raw_payload_id: UUID | None = None
    source_record_uid: str | None = None
    provenance: Provenance
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_flags: list[str] = Field(default_factory=list)
    normalizer_id: str
    normalizer_version: str
    normalization_run_id: UUID | None = None
    dedup_key: str
    replaces_observation_id: MeasurementId | None = None


def build_dedup_key(
    *,
    owner_id: object,
    workspace_id: object,
    source_id: object,
    metric_id: str,
    interval_start: datetime,
    interval_end: datetime,
    device_id: object | None = None,
    source_record_uid: str | None = None,
    value_repr: str = "",
) -> str:
    """Stable idempotency key for an observation.

    Prefers the upstream record's own uid when present; otherwise a deterministic
    hash over (owner, workspace, source, metric, interval, device, value). Mirrors
    Decision H's dedup strategy so re-ingest and replay converge on the same row.
    """
    if source_record_uid:
        basis = f"{owner_id}|{workspace_id}|{source_id}|{source_record_uid}"
    else:
        basis = "|".join(
            str(part)
            for part in (
                owner_id,
                workspace_id,
                source_id,
                metric_id,
                interval_start.isoformat(),
                interval_end.isoformat(),
                device_id or "",
                value_repr,
            )
        )
    return hashlib.sha256(basis.encode()).hexdigest()
