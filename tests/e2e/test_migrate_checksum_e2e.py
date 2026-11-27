"""E2E: the migration runner checksums applied files on real PostgreSQL.

The runner adds ``schema_migrations.checksum`` from its own bootstrap
(``ADD COLUMN IF NOT EXISTS``, no numbered migration), backfills it for rows
applied before checksums existed, and on an edited applied migration logs an
ERROR naming the file while the run still completes (the api waits on
``migrate``). Runs against the e2e database's real ``db/migrations``; every
file there is already tracked, so nothing is re-applied.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


async def _checksums() -> dict[str, str | None]:
    import asyncpg

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT filename, checksum FROM schema_migrations")
    finally:
        await conn.close()
    return {row["filename"]: row["checksum"] for row in rows}


async def _clear_checksum(filename: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE schema_migrations SET checksum = NULL WHERE filename = $1", filename
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_runner_backfills_checksums_and_reports_an_edited_file_without_failing(
    tmp_path: Path, caplog
) -> None:
    from db.migrate import apply_migrations, list_migrations, migration_checksum

    files = list_migrations(MIGRATIONS)
    target = files[0]

    # A row applied before checksums existed gets the file's checksum.
    await apply_migrations(DATABASE_URL, MIGRATIONS)
    await _clear_checksum(target.name)
    result = await apply_migrations(DATABASE_URL, MIGRATIONS)
    assert result.applied == []
    assert result.checksum_mismatches == []
    recorded = await _checksums()
    for path in files:
        assert recorded[path.name] == migration_checksum(path), path.name

    # The same set with one applied file edited: loud, listed, not fatal.
    edited_dir = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, edited_dir)
    edited = edited_dir / target.name
    edited.write_text(edited.read_text() + "\n-- edited after it was applied\n")
    with caplog.at_level(logging.INFO, logger="healthsave.db.migrate"):
        result = await apply_migrations(DATABASE_URL, edited_dir)

    assert result.applied == []
    assert result.checksum_mismatches == [target.name]
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and target.name in errors[0]
    # The recorded checksum is kept, so the next run raises the alarm again.
    assert (await _checksums())[target.name] == migration_checksum(target)
