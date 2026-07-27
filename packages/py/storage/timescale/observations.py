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
from sqlalchemy import bindparam, text

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
    semantic_key: str | None = None
    aggregation_scope: str = "interval_component"
    is_primary: bool = True


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
        "exact_ingest_key": obs.exact_ingest_key,
        "semantic_key": obs.semantic_key,
        "semantic_key_version": obs.semantic_key_version,
        "aggregation_scope": obs.aggregation_scope,
        "is_primary": obs.is_primary,
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
    semantic_key = row.get("semantic_key")
    return SeriesPoint(
        t=row["interval_start"],
        interval_end=row["interval_end"],
        value=row["numeric_value"],
        code=row["code"],
        unit=row["canonical_unit"],
        source_id=str(row["source_id"]),
        confidence=row["confidence"],
        stream_id=str(stream) if stream else None,
        semantic_key=str(semantic_key) if semantic_key else None,
        aggregation_scope=row.get("aggregation_scope") or "interval_component",
        is_primary=bool(row.get("is_primary", True)),
    )


_INSERT_SQL = text(
    """
    INSERT INTO canonical_observations (
        id, owner_id, workspace_id, metric_id, ontology_version, value_type,
        numeric_value, canonical_unit, code, components, value_json,
    interval_start, interval_end, recorded_at, source_id, device_id, stream_id,
    exact_ingest_key, semantic_key, semantic_key_version, aggregation_scope, is_primary,
    raw_payload_id, source_record_uid, confidence, quality_flags, provenance,
        normalizer_id, normalizer_version, normalization_run_id, dedup_key
    ) VALUES (
        :id, :owner_id, :workspace_id, :metric_id, :ontology_version, :value_type,
        :numeric_value, :canonical_unit, :code, CAST(:components AS JSONB),
        CAST(:value_json AS JSONB), :interval_start, :interval_end, :recorded_at,
    :source_id, :device_id, :stream_id, :exact_ingest_key, :semantic_key,
    :semantic_key_version, :aggregation_scope, :is_primary,
    :raw_payload_id, :source_record_uid, :confidence,
        :quality_flags, CAST(:provenance AS JSONB), :normalizer_id,
        :normalizer_version, :normalization_run_id, :dedup_key
    )
    ON CONFLICT (owner_id, workspace_id, dedup_key, interval_start) DO NOTHING
    """
)

_SERIES_SQL = text(
    """
    SELECT interval_start, interval_end, numeric_value, code, canonical_unit,
           source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
    FROM (
      SELECT interval_start, interval_end, numeric_value, code, canonical_unit,
             source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
      FROM canonical_observations
      WHERE owner_id = :owner_id
        AND workspace_id = :workspace_id
        AND metric_id = :metric_id
        AND interval_start >= :start
        AND interval_start < :end
        AND status = 'active'
        AND (CAST(:stream_id AS uuid) IS NULL OR stream_id = CAST(:stream_id AS uuid))
      ORDER BY interval_start DESC
      LIMIT :limit
    ) AS recent
    ORDER BY interval_start ASC
    """
)

_FUSED_SERIES_SQL = text(
    """
    WITH ranked AS (
      SELECT
        interval_start, interval_end, numeric_value, code, canonical_unit,
        source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary,
        ROW_NUMBER() OVER (
          PARTITION BY COALESCE(semantic_key, id::text)
          ORDER BY is_primary DESC, recorded_at DESC NULLS LAST, created_at DESC, id
        ) AS fusion_rank
      FROM canonical_observations
      WHERE owner_id = :owner_id
        AND workspace_id = :workspace_id
        AND metric_id = :metric_id
        AND interval_start >= :start
        AND interval_start < :end
        AND status = 'active'
        AND (CAST(:stream_id AS uuid) IS NULL OR stream_id = CAST(:stream_id AS uuid))
    ),
    recent AS (
      SELECT interval_start, interval_end, numeric_value, code, canonical_unit,
             source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
      FROM ranked
      WHERE fusion_rank = 1
      ORDER BY interval_start DESC
      LIMIT :limit
    )
    SELECT interval_start, interval_end, numeric_value, code, canonical_unit,
           source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
    FROM recent
    ORDER BY interval_start ASC
    """
)

_FUSED_SERIES_MANY_SQL = text(
    """
    WITH ranked AS (
      SELECT
        metric_id, interval_start, interval_end, numeric_value, code, canonical_unit,
        source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary,
        ROW_NUMBER() OVER (
          PARTITION BY metric_id, COALESCE(semantic_key, id::text)
          ORDER BY is_primary DESC, recorded_at DESC NULLS LAST, created_at DESC, id
        ) AS fusion_rank
      FROM canonical_observations
      WHERE owner_id = :owner_id
        AND workspace_id = :workspace_id
        AND metric_id IN :metric_ids
        AND interval_start >= :start
        AND interval_start < :end
        AND status = 'active'
        AND (CAST(:stream_id AS uuid) IS NULL OR stream_id = CAST(:stream_id AS uuid))
    ),
    fused AS (
      SELECT metric_id, interval_start, interval_end, numeric_value, code, canonical_unit,
             source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
      FROM ranked
      WHERE fusion_rank = 1
    ),
    capped AS (
      SELECT metric_id, interval_start, interval_end, numeric_value, code, canonical_unit,
             source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary,
             ROW_NUMBER() OVER (PARTITION BY metric_id ORDER BY interval_start DESC) AS rn
      FROM fused
    )
    SELECT metric_id, interval_start, interval_end, numeric_value, code, canonical_unit,
           source_id, stream_id, confidence, semantic_key, aggregation_scope, is_primary
    FROM capped
    WHERE rn <= :limit
    ORDER BY metric_id, interval_start ASC
    """
).bindparams(bindparam("metric_ids", expanding=True))


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

    async def query_fused_series(
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
        """Read series collapsed by ``semantic_key`` when fusion metadata exists.

        Rows without a ``semantic_key`` remain independent observations. Rows in
        the same semantic group keep one variant, preferring the row marked
        ``is_primary``.
        """
        result = await session.execute(
            _FUSED_SERIES_SQL,
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

    async def query_fused_series_many(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        metric_ids: list[str],
        start: datetime,
        end: datetime,
        limit: int = 5000,
        stream_id: str | None = None,
    ) -> dict[str, list[SeriesPoint]]:
        """Read fused series for several metrics in one round trip.

        Same fusion semantics as :meth:`query_fused_series` (collapse rows by
        ``semantic_key`` within a metric, preferring the row marked
        ``is_primary``), batched across ``metric_ids`` so the v2 batch route
        can replace its N sequential per-metric awaits with a single query.
        Fusion partitions by ``(metric_id, COALESCE(semantic_key, id::text))``
        so semantic keys never fuse across metrics, and the per-metric row
        cap is reapplied after fusion so each metric still yields at most
        ``limit`` rows. The cap keeps the newest rows, then presents them
        ascending by ``interval_start`` for chart consumers. Returns a dict keyed
        a metric with no rows in range is simply absent (the caller fills in
        ``[]``). Empty ``metric_ids`` returns ``{}`` without querying.
        """
        if not metric_ids:
            return {}
        result = await session.execute(
            _FUSED_SERIES_MANY_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "metric_ids": list(metric_ids),
                "start": start,
                "end": end,
                "limit": limit,
                "stream_id": str(stream_id) if stream_id else None,
            },
        )
        grouped: dict[str, list[SeriesPoint]] = {}
        for row in result.mappings().all():
            row = dict(row)
            grouped.setdefault(row["metric_id"], []).append(row_to_series_point(row))
        return grouped


default_repository = CanonicalObservationRepository()
