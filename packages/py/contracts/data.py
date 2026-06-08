# SPDX-License-Identifier: Apache-2.0
"""Health-data primitives — the v2 ingest plane in types.

Every measurement that lands in the system passes through this
shape, regardless of its source plugin. Source-specific weirdness
stays inside the source plugin; what crosses the plugin boundary
into the data plane is always a ``NormalizedMeasurement``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from ._base import (
    DeviceId,
    MeasurementId,
    Provenance,
    RunId,
    SourceId,
    V2Model,
    WithOwnership,
)


class Source(WithOwnership):
    """A source of health data — Apple HealthKit, Oura, manual log, etc."""

    id: SourceId
    plugin_id: str
    display_name: str
    kind: Literal["sensor", "manual", "computed", "external_api"]


class Device(WithOwnership):
    """A physical or logical device emitting samples for a Source."""

    id: DeviceId
    name: str
    source_id: SourceId
    model: str | None = None
    hardware_id: str | None = None


class RawSourcePayload(WithOwnership):
    """A payload as the source plugin received it, pre-normalization.

    Persisted before parsing so we can replay against new normalization
    code without re-fetching. ``payload_hash`` is sha256 of the canonical
    JSON form for dedup + idempotency.
    """

    id: UUID
    source_id: SourceId
    received_at: datetime
    payload_hash: str
    payload: dict


class NormalizedMeasurement(WithOwnership):
    """One canonical sample after a Source plugin has parsed it.

    Wraps a :class:`Measurement` and pins the raw payload it derives
    from. The split lets us evolve normalization independently of the
    canonical wire shape.
    """

    raw_payload_id: UUID
    measurement: Measurement


class Measurement(WithOwnership):
    """The canonical health measurement.

    Time-instant samples set ``interval_start == interval_end``.
    Time-interval samples (sleep stages, workouts, ECG) set both.
    """

    id: MeasurementId = Field(default_factory=uuid4)
    metric: str
    unit: str
    value: float
    interval_start: datetime
    interval_end: datetime
    source_id: SourceId
    device_id: DeviceId | None = None
    provenance: Provenance
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    normalization_version: str = "v1"


class SourceCapability(V2Model):
    """What a Source plugin claims it can produce.

    Declared in the plugin manifest; used by the ingestion runtime
    for scheduling and by the dashboard for "available sources" UI.
    """

    plugin_id: str
    metrics: list[str]
    delivery: Literal["polling", "webhook", "stream"]
    auth_required: bool = False
    rate_limit_per_minute: int | None = None


class IngestionRun(WithOwnership):
    """One execution of a Source plugin pulling/receiving data."""

    id: RunId
    source_id: SourceId
    started_at: datetime
    ended_at: datetime | None = None
    status: Literal["running", "succeeded", "failed", "partial", "cancelled"]
    measurements_count: int = 0
    errors_count: int = 0


class IngestionError(WithOwnership):
    """One error captured during an IngestionRun. Append-only."""

    id: UUID
    run_id: RunId
    occurred_at: datetime
    error_kind: str
    message: str
    payload_ref: str | None = None


# Resolve the forward ref — Measurement is declared after
# NormalizedMeasurement to keep the conceptual ordering, but Pydantic v2
# needs the explicit rebuild.
NormalizedMeasurement.model_rebuild()
