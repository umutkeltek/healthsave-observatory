"""Timescale persistence for lab results (Labs slice 1, migration 028).

All lab SQL lives here (storage zone). Callers pass an ``AsyncSession`` and own
the transaction, like every other timescale repository. Parsing, LOINC/UCUM
normalization and validation are pure and live in ``normalization.labs``; the
lab reading math is pure and lives in ``analysis.statistical.labs``. This module
only writes and reads rows.

Identity: the Source and one Stream per lab are registered through
``registry.record_origins`` (the same upsert the Apple path uses), so labs show
up next to wearables on the Sources surface.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    OperationalError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from . import registry


@dataclass(frozen=True, slots=True)
class LabResultWrite:
    """One normalized lab result, ready to persist (column-for-column)."""

    id: UUID
    metric_id: str
    loinc_code: str
    marker_name: str | None
    numeric_value: float
    value_comparator: str | None
    canonical_unit: str
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    specimen_at: datetime
    lab_name: str
    panel: str | None
    source_id: UUID
    source_plugin_id: str
    stream_id: UUID
    dedup_key: str
    semantic_key: str | None
    normalizer_id: str
    normalizer_version: str
    quality_flags: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LabResultRow:
    """One persisted, active lab result as read back."""

    id: UUID
    metric_id: str
    loinc_code: str
    marker_name: str | None
    numeric_value: float
    value_comparator: str | None
    canonical_unit: str
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    specimen_at: datetime
    lab_name: str
    panel: str | None
    source_plugin_id: str
    stream_id: UUID
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabImportSummary:
    """What an import changed. ``unchanged`` rows matched an existing row exactly."""

    inserted: int
    updated: int
    unchanged: int
    streams: int


# Upsert keyed on dedup_key (stream + LOINC + specimen time). A row whose
# value, unit, range or labels changed is updated and reported as such; an
# identical row is left alone (the WHERE suppresses the no-op update, so it
# returns no row and counts as "unchanged").
_UPSERT_SQL = text(
    """
    INSERT INTO lab_results (
        id, owner_id, workspace_id, metric_id, loinc_code, marker_name,
        numeric_value, value_comparator, canonical_unit,
        reference_low, reference_high, reference_text,
        interval_start, interval_end, lab_name, panel,
        source_id, source_plugin_id, stream_id, dedup_key, semantic_key,
        quality_flags, provenance, normalizer_id, normalizer_version
    ) VALUES (
        :id, :owner_id, :workspace_id, :metric_id, :loinc_code, :marker_name,
        :numeric_value, :value_comparator, :canonical_unit,
        :reference_low, :reference_high, :reference_text,
        :specimen_at, :specimen_at, :lab_name, :panel,
        :source_id, :source_plugin_id, :stream_id, :dedup_key, :semantic_key,
        :quality_flags, CAST(:provenance AS JSONB), :normalizer_id, :normalizer_version
    )
    ON CONFLICT (owner_id, workspace_id, dedup_key) DO UPDATE SET
        marker_name = EXCLUDED.marker_name,
        numeric_value = EXCLUDED.numeric_value,
        value_comparator = EXCLUDED.value_comparator,
        canonical_unit = EXCLUDED.canonical_unit,
        reference_low = EXCLUDED.reference_low,
        reference_high = EXCLUDED.reference_high,
        reference_text = EXCLUDED.reference_text,
        panel = EXCLUDED.panel,
        semantic_key = EXCLUDED.semantic_key,
        quality_flags = EXCLUDED.quality_flags,
        provenance = EXCLUDED.provenance,
        normalizer_id = EXCLUDED.normalizer_id,
        normalizer_version = EXCLUDED.normalizer_version,
        status = 'active',
        updated_at = now()
    WHERE (
        lab_results.marker_name, lab_results.numeric_value,
        lab_results.value_comparator, lab_results.canonical_unit,
        lab_results.reference_low, lab_results.reference_high,
        lab_results.reference_text, lab_results.panel, lab_results.status
    ) IS DISTINCT FROM (
        EXCLUDED.marker_name, EXCLUDED.numeric_value,
        EXCLUDED.value_comparator, EXCLUDED.canonical_unit,
        EXCLUDED.reference_low, EXCLUDED.reference_high,
        EXCLUDED.reference_text, EXCLUDED.panel, 'active'
    )
    RETURNING (xmax = 0) AS inserted
    """
)

_SELECT_COLS = (
    "id, metric_id, loinc_code, marker_name, numeric_value, value_comparator, "
    "canonical_unit, reference_low, reference_high, reference_text, "
    "interval_start AS specimen_at, lab_name, panel, source_plugin_id, stream_id, "
    "quality_flags"
)

_LIST_SQL = text(
    f"""
    SELECT {_SELECT_COLS}
    FROM lab_results
    WHERE owner_id = :owner_id
      AND workspace_id = :workspace_id
      AND status = 'active'
      AND (CAST(:loinc_code AS text) IS NULL OR loinc_code = CAST(:loinc_code AS text))
    ORDER BY loinc_code, interval_start, lab_name
    LIMIT :limit
    """
)


def _write_params(result: LabResultWrite, owner_id: UUID, workspace_id: UUID) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "owner_id": str(owner_id),
        "workspace_id": str(workspace_id),
        "metric_id": result.metric_id,
        "loinc_code": result.loinc_code,
        "marker_name": result.marker_name,
        "numeric_value": result.numeric_value,
        "value_comparator": result.value_comparator,
        "canonical_unit": result.canonical_unit,
        "reference_low": result.reference_low,
        "reference_high": result.reference_high,
        "reference_text": result.reference_text,
        "specimen_at": result.specimen_at,
        "lab_name": result.lab_name,
        "panel": result.panel,
        "source_id": str(result.source_id),
        "source_plugin_id": result.source_plugin_id,
        "stream_id": str(result.stream_id),
        "dedup_key": result.dedup_key,
        "semantic_key": result.semantic_key,
        "quality_flags": list(result.quality_flags),
        "provenance": json.dumps(dict(result.provenance), sort_keys=True, default=str),
        "normalizer_id": result.normalizer_id,
        "normalizer_version": result.normalizer_version,
    }


def _row(row: Any) -> LabResultRow:
    return LabResultRow(
        id=row.id if isinstance(row.id, UUID) else UUID(str(row.id)),
        metric_id=row.metric_id,
        loinc_code=row.loinc_code,
        marker_name=row.marker_name,
        numeric_value=float(row.numeric_value),
        value_comparator=row.value_comparator,
        canonical_unit=row.canonical_unit,
        reference_low=None if row.reference_low is None else float(row.reference_low),
        reference_high=None if row.reference_high is None else float(row.reference_high),
        reference_text=row.reference_text,
        specimen_at=row.specimen_at,
        lab_name=row.lab_name,
        panel=row.panel,
        source_plugin_id=row.source_plugin_id,
        stream_id=row.stream_id if isinstance(row.stream_id, UUID) else UUID(str(row.stream_id)),
        quality_flags=tuple(row.quality_flags or ()),
    )


class TimescaleLabRepository:
    """Write + read side of ``lab_results``."""

    async def import_results(
        self,
        session: AsyncSession,
        results: Sequence[LabResultWrite],
        *,
        plugin_id: str,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    ) -> LabImportSummary:
        """Register the Source + one Stream per lab, then upsert every result.

        Idempotent: re-importing the same rows changes nothing and reports them
        as ``unchanged``. The caller owns the transaction (commit/rollback), so
        an import is all-or-nothing when the caller commits once at the end.
        """
        if not results:
            return LabImportSummary(inserted=0, updated=0, unchanged=0, streams=0)
        streams = await registry.record_origins(
            session,
            owner_id=owner_id,
            plugin_id=plugin_id,
            origins=[result.lab_name for result in results],
        )
        inserted = updated = 0
        for result in results:
            outcome = await session.execute(
                _UPSERT_SQL, _write_params(result, owner_id, workspace_id)
            )
            row = outcome.first()
            if row is None:
                continue
            if row.inserted:
                inserted += 1
            else:
                updated += 1
        return LabImportSummary(
            inserted=inserted,
            updated=updated,
            unchanged=len(results) - inserted - updated,
            streams=streams,
        )

    async def list_results(
        self,
        session: AsyncSession,
        *,
        owner_id: UUID = DEFAULT_OWNER_ID,
        workspace_id: UUID = DEFAULT_WORKSPACE_ID,
        loinc_code: str | None = None,
        limit: int = 5000,
    ) -> list[LabResultRow]:
        """Active results, ordered by marker, then specimen time, then lab."""
        result = await session.execute(
            _LIST_SQL,
            {
                "owner_id": str(owner_id),
                "workspace_id": str(workspace_id),
                "loinc_code": loinc_code,
                "limit": limit,
            },
        )
        return [_row(row) for row in result.fetchall()]


# Transient infra failures a retry can clear. Everything else that goes wrong
# while writing a validated file is deterministic and must not be retried in a
# loop. Mirrors the deny-list in server.api.ingest (note: SQLAlchemy's pool
# TimeoutError is not the builtin TimeoutError).
_TRANSIENT_DB_ERRORS = (
    OperationalError,
    InterfaceError,
    SQLAlchemyTimeoutError,
    DisconnectionError,
    TimeoutError,
    ConnectionError,
    OSError,
)


def is_transient_db_error(exc: BaseException) -> bool:
    """True when retrying the same write could succeed (database unreachable,
    pool exhausted, deadlock); False for deterministic failures."""
    if isinstance(exc, _TRANSIENT_DB_ERRORS):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) in {"40P01", "40001"}:
        return True
    return bool(getattr(exc, "connection_invalidated", False))


default_repository = TimescaleLabRepository()

__all__ = [
    "LabImportSummary",
    "LabResultRow",
    "LabResultWrite",
    "TimescaleLabRepository",
    "default_repository",
    "is_transient_db_error",
]
