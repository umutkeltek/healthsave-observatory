"""PostgreSQL proof for migration 028 + the lab_results repository.

The unit suite drives the repository against a fake session. This test runs the
real upsert against the ephemeral E2E database (migrations applied by the
compose ``migrate`` service): first import inserts, an identical re-import is a
no-op, a corrected value is an update, and the Source + per-lab Streams land in
the identity registry. Each run uses its own owner id and removes its rows.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest
from normalization import identity
from storage.timescale.labs import LabResultWrite, TimescaleLabRepository

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="set E2E_DATABASE_URL to run the lab_results proof (see `make e2e`)",
    ),
]

PLUGIN = "labs-csv"


def _results(owner, *, ferritin: float = 41.0) -> list[LabResultWrite]:
    rows = []
    for lab, loinc, name, value, unit, low, high, day in (
        ("Northfield Lab", "2276-4", "Ferritin", ferritin, "ng/mL", 30.0, 400.0, 12),
        ("Northfield Lab", "718-7", "Hemoglobin", 14.1, "g/dL", 13.5, 17.5, 12),
        ("Harbor Clinic Lab", "2276-4", "Ferritin", 38.0, "ng/mL", 22.0, 322.0, 14),
    ):
        stream = identity.stream_id(owner, PLUGIN, identity.normalize_origin(lab))
        specimen = datetime(2026, 3, day, 8, 0, tzinfo=UTC)
        key = f"e2e:{stream}:{loinc}:{specimen.isoformat()}"
        rows.append(
            LabResultWrite(
                id=uuid5(identity.STREAM_NAMESPACE, f"{owner}:{key}"),
                metric_id=f"loinc:{loinc}",
                loinc_code=loinc,
                marker_name=name,
                numeric_value=value,
                value_comparator=None,
                canonical_unit=unit,
                reference_low=low,
                reference_high=high,
                reference_text=f"{low}-{high}",
                specimen_at=specimen,
                lab_name=lab,
                panel=None,
                source_id=identity.source_uuid(owner, PLUGIN),
                source_plugin_id=PLUGIN,
                stream_id=stream,
                dedup_key=key,
                semantic_key=None,
                normalizer_id=PLUGIN,
                normalizer_version="1",
                provenance={"row": 2},
            )
        )
    return rows


@pytest.mark.asyncio
async def test_lab_results_upsert_is_idempotent_and_registers_identity() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    owner = uuid4()
    repo = TimescaleLabRepository()
    try:
        async with AsyncSession(engine) as session:
            first = await repo.import_results(
                session, _results(owner), plugin_id=PLUGIN, owner_id=owner
            )
            await session.commit()
            again = await repo.import_results(
                session, _results(owner), plugin_id=PLUGIN, owner_id=owner
            )
            await session.commit()
            corrected = await repo.import_results(
                session, _results(owner, ferritin=44.0), plugin_id=PLUGIN, owner_id=owner
            )
            await session.commit()

            assert (first.inserted, first.updated, first.unchanged) == (3, 0, 0)
            assert first.streams == 2
            assert (again.inserted, again.updated, again.unchanged) == (0, 0, 3)
            assert (corrected.inserted, corrected.updated, corrected.unchanged) == (0, 1, 2)

            rows = await repo.list_results(session, owner_id=owner)
            assert [(r.loinc_code, r.lab_name, r.numeric_value) for r in rows] == [
                ("2276-4", "Northfield Lab", 44.0),
                ("2276-4", "Harbor Clinic Lab", 38.0),
                ("718-7", "Northfield Lab", 14.1),
            ]
            ferritin = await repo.list_results(session, owner_id=owner, loinc_code="2276-4")
            assert len(ferritin) == 2

            streams = await session.execute(
                text(
                    "SELECT device_label FROM source_device_streams "
                    "WHERE owner_id = :owner AND source_plugin_id = :plugin ORDER BY 1"
                ),
                {"owner": str(owner), "plugin": PLUGIN},
            )
            assert [row[0] for row in streams] == ["Harbor Clinic Lab", "Northfield Lab"]
    finally:
        async with AsyncSession(engine) as session:
            for table, column in (
                ("lab_results", "owner_id"),
                ("source_device_streams", "owner_id"),
                ("sources", "owner_id"),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :owner"), {"owner": str(owner)}
                )
            await session.commit()
        await engine.dispose()
