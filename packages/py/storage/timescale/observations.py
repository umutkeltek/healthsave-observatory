"""TimescaleDB adapter for the canonical Observation store (Decision C).

Persists canonical :class:`contracts.observation.Observation` records into
``canonical_observations`` (migration 012) and reads metric time-series back
out. The value tagged-union is flattened onto typed columns at write time
(numeric_value / code / components / value_json) so hot scalar reads stay on an
indexed column; the read side is what the v2 API and the LLM narrator consume.

Mapping helpers are pure (no session) so they unit-test without a database;
the repository methods take an ``AsyncSession`` the caller owns, per the
storage-port discipline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from contracts.observation import Observation
from sqlalchemy import text

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SeriesPoint:
    """One point on a metric series — scalar or coded, with provenance."""

    t: datetime
    interval_end: datetime
    value: float | None
    code: str | None
    unit: str | None
    source_id: str
    confidence: float | None
    stream_id: str | None = None


def observation_columns(obs: Observation) -> dict[str, Any]:
    """Flatten an Observation onto canonical_observations columns (pure)."""
    numeric_value: float | None = None
    code: str | None = None
    components: str | None = None
    value_json: str | None = None
    canonical_unit: str | None = None

    value = obs.value
    if value.type == "quantity":
        numeric_value = value.canonical_value
        canonical_unit = value.canonical_unit
    elif value.type == "categorical":
        code = value.code
    elif value.type == "boolean":
        numeric_value = 1.0 if value.value else 0.0
    elif value.type == "components":
        components = value.model_dump_json()
    else:  # event / waveform / json
        value_json = value.model_dump_json()

    return {
        "id": str(obs.id),
        "owner_id": str(obs.owner_id),
        "workspace_id": str(obs.workspace_id),
        "metric_id": obs.metric_id,
        "ontology_version": obs.ontology_version,
        "value_type": value.type,
        "numeric_value": numeric_value,
        "canonical_unit": canonical_unit,
        "code": code,
        "components": components,
        "value_json": value_json,
        "interval_start": obs.interval_start,
        "interval_end": obs.interval_end,
        "recorded_at": obs.recorded_at,
        "source_id": str(obs.source_id),
        "device_id": str(obs.device_id) if obs.device_id else None,
        "stream_id": str(obs.stream_id) if obs.stream_id else None,
        "raw_payload_id": str(obs.raw_payload_id) if obs.raw_payload_id else None,
        "source_record_uid": obs.source_record_uid,
        "confidence": obs.confidence,
        "quality_flags": list(obs.quality_flags),
        "provenance": obs.provenance.model_dump_json(),
        "normalizer_id": obs.normalizer_id,
        "normalizer_version": obs.normalizer_version,
        "normalization_run_id": str(obs.normalization_run_id) if obs.normalization_run_id else None,
        "dedup_key": obs.dedup_key,
    }


def row_to_series_point(row: dict[str, Any]) -> SeriesPoint:
    """Map a query row mapping to a SeriesPoint (pure)."""
    stream = row.get("stream_id")
    return SeriesPoint(
        t=row["interval_start"],
        interval_end=row["interval_end"],
        value=row["numeric_value"],
        code=row["code"],
        unit=row["canonical_unit"],
        source_id=str(row["source_id"]),
        confidence=row["confidence"],
        stream_id=str(stream) if stream else None,
    )


_INSERT_SQL = text(
    """
    INSERT INTO canonical_observations (
        id, owner_id, workspace_id, metric_id, ontology_version, value_type,
        numeric_value, canonical_unit, code, components, value_json,
        interval_start, interval_end, recorded_at, source_id, device_id, stream_id,
        raw_payload_id, source_record_uid, confidence, quality_flags, provenance,
        normalizer_id, normalizer_version, normalization_run_id, dedup_key
    ) VALUES (
        :id, :owner_id, :workspace_id, :metric_id, :ontology_version, :value_type,
        :numeric_value, :canonical_unit, :code, CAST(:components AS JSONB),
        CAST(:value_json AS JSONB), :interval_start, :interval_end, :recorded_at,
        :source_id, :device_id, :stream_id, :raw_payload_id, :source_record_uid, :confidence,
        :quality_flags, CAST(:provenance AS JSONB), :normalizer_id,
        :normalizer_version, :normalization_run_id, :dedup_key
    )
    ON CONFLICT (owner_id, workspace_id, dedup_key, interval_start) DO NOTHING
    """
)

_SERIES_SQL = text(
    """
    SELECT interval_start, interval_end, numeric_value, code, canonical_unit,
           source_id, stream_id, confidence
    FROM canonical_observations
    WHERE owner_id = :owner_id
      AND workspace_id = :workspace_id
      AND metric_id = :metric_id
      AND interval_start >= :start
      AND interval_start < :end
      AND status = 'active'
      AND (CAST(:stream_id AS uuid) IS NULL OR stream_id = CAST(:stream_id AS uuid))
    ORDER BY interval_start ASC
    LIMIT :limit
    """
)


class CanonicalObservationRepository:
    """Write + read side of the canonical Observation store."""

    async def insert_many(self, session: AsyncSession, observations: list[Observation]) -> int:
        """Idempotently persist observations. Returns the count submitted."""
        if not observations:
            return 0
        rows = [observation_columns(obs) for obs in observations]
        await session.execute(_INSERT_SQL, rows)
        return len(rows)

    async def query_series(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        metric_id: str,
        start: datetime,
        end: datetime,
        limit: int = 5000,
        stream_id: str | None = None,
    ) -> list[SeriesPoint]:
        """Read one metric's active series within [start, end).

        ``stream_id`` optionally narrows to a single device stream; ``None``
        returns the fused series across all streams (unchanged behavior).
        """
        result = await session.execute(
            _SERIES_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "metric_id": metric_id,
                "start": start,
                "end": end,
                "limit": limit,
                "stream_id": str(stream_id) if stream_id else None,
            },
        )
        return [row_to_series_point(dict(row)) for row in result.mappings().all()]
