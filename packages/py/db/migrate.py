"""Idempotent SQL migration runner.

Discovers every ``db/migrations/*.sql`` file under a given directory,
applies the ones not yet recorded in the ``schema_migrations`` tracking
table, and records each successful apply atomically with the migration
DDL itself.

Design choices:

  * **One file = one migration.** Filenames sort alphabetically; the
    ``NNN_name.sql`` convention keeps numeric ordering well-formed.
  * **Tracking table is the source of truth.** A migration runs iff its
    filename is missing from ``schema_migrations``. We do NOT rely on
    ``IF NOT EXISTS`` per-statement to skip applied migrations — that
    would silently mask non-idempotent migrations (a future ``DROP
    COLUMN`` or data backfill). Idempotency inside a migration is a
    *defense-in-depth* habit, not the safety mechanism.
  * **Atomic per-migration transaction.** A failure inside one
    migration rolls back BOTH the DDL and the ``schema_migrations``
    insert, so re-running picks up exactly where it left off.
  * **Baseline-safe.** First run against an existing DB (where
    schema.sql has already been applied) creates ``schema_migrations``,
    finds it empty, and tries every migration. The existing migrations
    are written with ``IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS``,
    so they no-op on already-applied schema and end up tracked. After
    that first run, the table reflects reality.
  * **Edited applied migrations are noticed, not fatal.** Each row
    carries the sha256 of the file as it was applied. A tracked row
    with no checksum (applied before checksums existed) gets the
    current file's on the next run. A file whose checksum no longer
    matches is logged as an ERROR naming it and listed in
    :attr:`MigrationResult.checksum_mismatches`, and the run carries
    on: compose starts the api only after ``migrate`` completes, so
    failing here would take a live install down over a file that has
    already done its work. The recorded checksum is left in place so
    the alarm repeats on every run until someone acts on it.

Driver choice: asyncpg directly, not SQLAlchemy. Migrations are SQL
files that often carry multiple statements (DO $$ ... $$ blocks,
CHECK constraints, indexes after CREATE TABLE). asyncpg's
``Connection.execute`` natively handles multi-statement SQL; the
SQLAlchemy ``text()`` wrapper does not consistently.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("healthsave.db.migrate")


# The checksum column is added here, not by a numbered migration: the
# tracking table belongs to the runner, and a migration cannot describe the
# table that decides whether it runs.
_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT;
"""
_LOCK_SQL = "SELECT pg_advisory_lock(753266010001)"
_UNLOCK_SQL = "SELECT pg_advisory_unlock(753266010001)"


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of one :func:`apply_migrations` call.

    ``applied`` lists filenames that ran successfully in this invocation
    (and are now in ``schema_migrations``). ``skipped`` lists filenames
    that were already tracked before the call. ``checksum_mismatches``
    lists tracked filenames whose file changed after it was applied.
    """

    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    checksum_mismatches: list[str] = field(default_factory=list)


class _Transaction(Protocol):
    async def __aenter__(self) -> Any: ...
    async def __aexit__(self, *exc_info: Any) -> Any: ...


class _Connection(Protocol):
    """Minimum surface migrate uses from an asyncpg.Connection.

    Tests substitute a recording double that satisfies this Protocol.
    """

    async def execute(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    def transaction(self) -> _Transaction: ...
    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[_Connection]]
"""Callable that opens a connection to the given URL. ``asyncpg.connect``
matches this signature; tests inject a recording double."""


def list_migrations(migrations_dir: Path) -> list[Path]:
    """Return ``*.sql`` files in alphabetical (= numeric-prefix) order.

    A missing directory returns an empty list — running with no
    migrations on disk is a no-op, not an error.
    """
    if not migrations_dir.is_dir():
        return []
    return sorted(migrations_dir.glob("*.sql"))


def migration_checksum(path: Path) -> str:
    """sha256 of the migration file exactly as shipped (hex)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_significant_sql_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("--")


def _migration_sql(path: Path) -> str:
    sql = path.read_text(encoding="utf-8")
    lines = sql.splitlines()
    first_sql = next(
        (index for index, line in enumerate(lines) if _is_significant_sql_line(line)),
        None,
    )
    last_sql = next(
        (
            index
            for index, line in reversed(list(enumerate(lines)))
            if _is_significant_sql_line(line)
        ),
        None,
    )

    if (
        first_sql is not None
        and last_sql is not None
        and lines[first_sql].strip().upper() == "BEGIN;"
        and lines[last_sql].strip().upper() == "COMMIT;"
    ):
        return "\n".join([*lines[:first_sql], *lines[first_sql + 1 : last_sql]]).strip()
    return sql.strip()


async def _default_connect(url: str) -> _Connection:  # pragma: no cover
    import asyncpg

    # SQLAlchemy uses 'postgresql+asyncpg://' but asyncpg.connect wants
    # 'postgresql://'. Normalize so callers can pass DATABASE_URL verbatim.
    normalized = url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(normalized)


async def apply_migrations(
    database_url: str,
    migrations_dir: Path,
    *,
    connect: Connector | None = None,
) -> MigrationResult:
    """Apply every untracked migration under ``migrations_dir``.

    Returns a :class:`MigrationResult` listing filenames applied + skipped.
    """
    connector = connect or _default_connect
    conn = await connector(database_url)
    locked = False
    try:
        await conn.execute(_LOCK_SQL)
        locked = True
        await conn.execute(_BOOTSTRAP_SQL)
        rows = await conn.fetch("SELECT filename, checksum FROM schema_migrations")
        already_applied = {row["filename"]: row["checksum"] for row in rows}

        applied: list[str] = []
        skipped: list[str] = []
        mismatches: list[str] = []
        backfilled = 0
        for path in list_migrations(migrations_dir):
            checksum = migration_checksum(path)
            if path.name in already_applied:
                skipped.append(path.name)
                recorded = already_applied[path.name]
                if recorded is None:
                    await conn.execute(
                        "UPDATE schema_migrations SET checksum = $2 "
                        "WHERE filename = $1 AND checksum IS NULL",
                        path.name,
                        checksum,
                    )
                    backfilled += 1
                elif recorded != checksum:
                    mismatches.append(path.name)
                    log.error(
                        "MIGRATION CHECKSUM MISMATCH: %s was edited after it was applied "
                        "(recorded sha256 %s, file now %s). An applied migration must never "
                        "be edited: restore the file and put the change in a new migration. "
                        "Continuing; this file is not re-run.",
                        path.name,
                        recorded,
                        checksum,
                    )
                continue
            log.info("applying %s", path.name)
            sql = _migration_sql(path)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2) "
                    "ON CONFLICT (filename) DO NOTHING",
                    path.name,
                    checksum,
                )
            applied.append(path.name)
        if backfilled:
            log.info("migrations: recorded checksums for %d already-applied file(s)", backfilled)
        if applied:
            log.info(
                "migrations: %d applied (%s), %d already up-to-date",
                len(applied),
                ", ".join(applied),
                len(skipped),
            )
        else:
            log.info("migrations: schema already up-to-date (%d tracked)", len(skipped))
        return MigrationResult(applied=applied, skipped=skipped, checksum_mismatches=mismatches)
    finally:
        if locked:
            await conn.execute(_UNLOCK_SQL)
        await conn.close()
