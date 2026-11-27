"""PostgreSQL proof for migration 028 + the lab_results repository.

The unit suite drives the repository against a fake session. This test runs the
real upsert against the ephemeral E2E database (migrations applied by the
compose ``migrate`` service): first import inserts, an identical re-import is a
no-op, a corrected value is an update, and the Source + per-lab Streams land in
the identity registry. Each run uses its own owner id and removes its rows.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


BASE_URL = os.getenv("E2E_BASE_URL")
SAMPLE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "labs", "sample_labs.csv")


@pytest.mark.asyncio
@pytest.mark.skipif(not BASE_URL, reason="set E2E_BASE_URL + E2E_DATABASE_URL (see `make e2e`)")
async def test_imported_sample_reads_back_through_the_v2_labs_routes() -> None:
    """Import the synthetic sample with the real CLI module, then read it over HTTP."""
    import httpx
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": os.pathsep.join(sys.path)}
    headers = {"X-API-Key": os.environ["E2E_API_KEY"]} if os.getenv("E2E_API_KEY") else {}
    engine = create_async_engine(url)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.import_labs", SAMPLE],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert "12 result(s)" in proc.stdout

        async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=10) as client:
            overview = (await client.get("/api/v2/labs")).json()
            ferritin = (await client.get("/api/v2/labs/2276-4")).json()
            bad = await client.get("/api/v2/labs/2276-5")

        assert overview["result_count"] >= 12
        assert {"Northfield Diagnostics", "Harbor Clinical Lab"} <= {
            lab["lab"] for lab in overview["labs"]
        }
        labs_in_series = [r["lab"] for r in ferritin["results"]]
        assert labs_in_series.count("Northfield Diagnostics") >= 3
        assert "Harbor Clinical Lab" in labs_in_series
        assert bad.status_code == 422
    finally:
        async with AsyncSession(engine) as session:
            await session.execute(
                text("DELETE FROM lab_results WHERE provenance->>'file_name' = 'sample_labs.csv'")
            )
            await session.commit()
        await engine.dispose()
