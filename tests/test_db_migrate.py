from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pytest
from db.migrate import apply_migrations, list_migrations


class RecordingTransaction:
    def __init__(self, conn: RecordingConnection) -> None:
        self.conn = conn

    async def __aenter__(self) -> None:
        self.conn.events.append(("transaction_enter", None))

    async def __aexit__(self, *exc_info: Any) -> None:
        self.conn.events.append(("transaction_exit", exc_info[0]))


class RecordingConnection:
    def __init__(
        self,
        *,
        applied: set[str] | dict[str, str | None] | None = None,
        fail_on_sql: str | None = None,
    ) -> None:
        # A set means tracked rows with no recorded checksum (the pre-checksum
        # table); a dict maps each tracked filename to its stored checksum.
        if isinstance(applied, dict):
            self.applied = dict(applied)
        else:
            self.applied = dict.fromkeys(applied or set())
        self.fail_on_sql = fail_on_sql
        self.events: list[tuple[str, Any]] = []
        self.closed = False

    async def execute(self, query: str, *args: Any) -> str:
        self.events.append(("execute", (query, args)))
        if self.fail_on_sql and self.fail_on_sql in query:
            raise RuntimeError("boom")
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, str]]:
        self.events.append(("fetch", (query, args)))
        return [
            {"filename": filename, "checksum": checksum}
            for filename, checksum in sorted(self.applied.items())
        ]

    def transaction(self) -> RecordingTransaction:
        return RecordingTransaction(self)

    async def close(self) -> None:
        self.closed = True
        self.events.append(("close", None))


def write_migration(directory: Path, filename: str, sql: str) -> Path:
    path = directory / filename
    path.write_text(sql)
    return path


def executed_sql(conn: RecordingConnection) -> list[str]:
    return [
        query for event, payload in conn.events if event == "execute" for query, _args in [payload]
    ]


def executed(conn: RecordingConnection, fragment: str) -> list[tuple[str, tuple]]:
    return [
        (query, args)
        for event, payload in conn.events
        if event == "execute"
        for query, args in [payload]
        if fragment in query
    ]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connector_for(conn: RecordingConnection):
    async def connect(_url: str) -> RecordingConnection:
        return conn

    return connect


def test_list_migrations_returns_sql_files_in_filename_order(tmp_path: Path) -> None:
    write_migration(tmp_path, "010_later.sql", "SELECT 10;")
    write_migration(tmp_path, "002_middle.sql", "SELECT 2;")
    (tmp_path / "README.md").write_text("not a migration")

    assert [path.name for path in list_migrations(tmp_path)] == [
        "002_middle.sql",
        "010_later.sql",
    ]


@pytest.mark.asyncio
async def test_apply_migrations_runs_only_untracked_files_and_records_them(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_done.sql", "SELECT 1;")
    write_migration(tmp_path, "002_new.sql", "SELECT 2;")
    conn = RecordingConnection(applied={"001_done.sql"})

    result = await apply_migrations(
        "postgresql+asyncpg://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    assert result.applied == ["002_new.sql"]
    assert result.skipped == ["001_done.sql"]
    assert any("SELECT 2" in query for query in executed_sql(conn))
    assert not any("SELECT 1" in query for query in executed_sql(conn))
    assert conn.closed is True


@pytest.mark.asyncio
async def test_apply_migrations_serializes_runners_with_advisory_lock(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_new.sql", "SELECT 1;")
    conn = RecordingConnection()

    await apply_migrations(
        "postgresql://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    queries = executed_sql(conn)
    assert "SELECT pg_advisory_lock" in queries[0]
    assert "SELECT pg_advisory_unlock" in queries[-1]


@pytest.mark.asyncio
async def test_apply_migrations_strips_top_level_transaction_wrappers(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "001_wrapped.sql",
        """
BEGIN;
CREATE TABLE example(id INTEGER);
COMMIT;
""",
    )
    conn = RecordingConnection()

    await apply_migrations(
        "postgresql://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    migration_queries = [query for query in executed_sql(conn) if "CREATE TABLE example" in query]
    assert migration_queries == ["CREATE TABLE example(id INTEGER);"]


@pytest.mark.asyncio
async def test_apply_migrations_strips_transaction_wrappers_after_header_comments(
    tmp_path: Path,
) -> None:
    write_migration(
        tmp_path,
        "001_wrapped_with_comments.sql",
        """
-- 001_wrapped_with_comments.sql
--
-- Existing project migrations carry explanatory headers.

BEGIN;
CREATE TABLE example_with_comments(id INTEGER);
COMMIT;
""",
    )
    conn = RecordingConnection()

    await apply_migrations(
        "postgresql://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    migration_queries = [
        query for query in executed_sql(conn) if "CREATE TABLE example_with_comments" in query
    ]
    assert "BEGIN;" not in migration_queries[0]
    assert "COMMIT;" not in migration_queries[0]


@pytest.mark.asyncio
async def test_apply_migrations_does_not_record_failed_migration(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_bad.sql", "SELECT explode;")
    conn = RecordingConnection(fail_on_sql="explode")

    with pytest.raises(RuntimeError, match="boom"):
        await apply_migrations(
            "postgresql://user:pass@db:5432/healthsave",
            tmp_path,
            connect=connector_for(conn),
        )

    assert not any("INSERT INTO schema_migrations" in query for query in executed_sql(conn))
    assert conn.closed is True


def test_list_migrations_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    """The runner is a no-op on a fresh checkout with no migrations
    on disk. Don't blow up on missing dir.
    """
    assert list_migrations(tmp_path / "does-not-exist") == []


@pytest.mark.asyncio
async def test_apply_migrations_is_a_clean_noop_when_everything_tracked(
    tmp_path: Path,
) -> None:
    """All migrations already tracked: no DDL runs, no INSERT runs,
    but the advisory lock still gets acquired and released.

    This is the steady-state every datahub container start hits once
    the schema is current — locking is cheap and stays in the path so
    the lock pattern can't silently rot.
    """
    write_migration(tmp_path, "001_a.sql", "SELECT 1;")
    write_migration(tmp_path, "002_b.sql", "SELECT 2;")
    conn = RecordingConnection(applied={"001_a.sql", "002_b.sql"})

    result = await apply_migrations(
        "postgresql://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    assert result.applied == []
    assert result.skipped == ["001_a.sql", "002_b.sql"]

    queries = executed_sql(conn)
    assert "SELECT pg_advisory_lock" in queries[0]
    assert "SELECT pg_advisory_unlock" in queries[-1]
    assert not any("SELECT 1" in q or "SELECT 2" in q for q in queries)
    assert not any("INSERT INTO schema_migrations" in q for q in queries)


@pytest.mark.asyncio
async def test_apply_migrations_preserves_inner_do_blocks_without_outer_wrapper(
    tmp_path: Path,
) -> None:
    """The BEGIN/COMMIT strip heuristic must be conservative.

    A migration whose body uses ``DO $$ BEGIN ... END $$;`` (a PL/pgSQL
    block — NOT a transaction) must NOT have its inner BEGIN/END
    touched. We only strip the *outer* `BEGIN;` / `COMMIT;` and only
    when both bookend the file. This test pins that contract: a file
    that contains a DO block but no outer transaction wrapper round-
    trips its full body to the connection.
    """
    body = """
-- A migration using a PL/pgSQL block (not a transaction).
DO $$ BEGIN
    PERFORM 1;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
""".strip()
    write_migration(tmp_path, "001_do_block.sql", body + "\n")
    conn = RecordingConnection()

    await apply_migrations(
        "postgresql://user:pass@db:5432/healthsave",
        tmp_path,
        connect=connector_for(conn),
    )

    queries = executed_sql(conn)
    migration_queries = [q for q in queries if "PERFORM 1" in q]
    assert len(migration_queries) == 1
    assert "DO $$ BEGIN" in migration_queries[0]
    assert "EXCEPTION WHEN duplicate_object THEN NULL;" in migration_queries[0]
    assert "END $$;" in migration_queries[0]


def test_canonical_fusion_metadata_migration_is_additive() -> None:
    migration = Path("db/migrations/020_canonical_fusion_metadata.sql")
    text = migration.read_text()

    for column in (
        "exact_ingest_key",
        "semantic_key",
        "semantic_key_version",
        "aggregation_scope",
        "is_primary",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in text

    assert "CREATE TABLE IF NOT EXISTS fusion_decisions" in text
    assert "CREATE TABLE IF NOT EXISTS device_identity_links" in text
    assert "idx_canonical_obs_semantic_key" in text
    assert "DROP " not in text.upper()


# ── checksums: an edited applied migration is noticed, never fatal ────


@pytest.mark.asyncio
async def test_bootstrap_adds_the_checksum_column_under_the_lock(tmp_path: Path) -> None:
    conn = RecordingConnection()

    await apply_migrations("postgresql://u:p@db/h", tmp_path, connect=connector_for(conn))

    queries = executed_sql(conn)
    assert "pg_advisory_lock" in queries[0]
    bootstrap = next(q for q in queries if "CREATE TABLE IF NOT EXISTS schema_migrations" in q)
    assert "ADD COLUMN IF NOT EXISTS checksum" in bootstrap
    assert queries.index(bootstrap) > 0


@pytest.mark.asyncio
async def test_applied_migration_records_the_sha256_of_its_file(tmp_path: Path) -> None:
    path = write_migration(tmp_path, "001_new.sql", "-- header\nBEGIN;\nSELECT 1;\nCOMMIT;\n")
    conn = RecordingConnection()

    await apply_migrations("postgresql://u:p@db/h", tmp_path, connect=connector_for(conn))

    [(query, args)] = executed(conn, "INSERT INTO schema_migrations")
    assert "checksum" in query
    # The whole file as shipped, not the BEGIN/COMMIT-stripped body.
    assert args == ("001_new.sql", sha256_of(path))


@pytest.mark.asyncio
async def test_tracked_migration_without_a_checksum_is_backfilled(tmp_path: Path) -> None:
    path = write_migration(tmp_path, "001_old.sql", "SELECT 1;")
    conn = RecordingConnection(applied={"001_old.sql"})  # no checksum recorded

    result = await apply_migrations("postgresql://u:p@db/h", tmp_path, connect=connector_for(conn))

    assert result.applied == []
    assert result.checksum_mismatches == []
    [(query, args)] = executed(conn, "UPDATE schema_migrations")
    assert "checksum IS NULL" in query  # never overwrites a recorded one
    assert args == ("001_old.sql", sha256_of(path))


@pytest.mark.asyncio
async def test_matching_checksum_is_quiet(tmp_path: Path, caplog) -> None:
    path = write_migration(tmp_path, "001_old.sql", "SELECT 1;")
    conn = RecordingConnection(applied={"001_old.sql": sha256_of(path)})

    with caplog.at_level(logging.INFO, logger="healthsave.db.migrate"):
        result = await apply_migrations(
            "postgresql://u:p@db/h", tmp_path, connect=connector_for(conn)
        )

    assert result.checksum_mismatches == []
    assert executed(conn, "UPDATE schema_migrations") == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_edited_applied_migration_logs_a_loud_error_and_the_run_continues(
    tmp_path: Path, caplog
) -> None:
    write_migration(tmp_path, "001_edited.sql", "SELECT 1; -- edited after it shipped")
    write_migration(tmp_path, "002_new.sql", "SELECT 2;")
    recorded = "0" * 64
    conn = RecordingConnection(applied={"001_edited.sql": recorded})

    with caplog.at_level(logging.INFO, logger="healthsave.db.migrate"):
        result = await apply_migrations(
            "postgresql://u:p@db/h", tmp_path, connect=connector_for(conn)
        )

    # Not fatal: the api waits on migrate, so a raise would take the stack down.
    assert result.applied == ["002_new.sql"]
    assert result.checksum_mismatches == ["001_edited.sql"]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "001_edited.sql" in errors[0].getMessage()
    # The recorded checksum stays, so the alarm repeats until someone acts.
    assert executed(conn, "UPDATE schema_migrations") == []
    assert "pg_advisory_unlock" in executed_sql(conn)[-1]
    assert conn.closed is True


@pytest.mark.asyncio
async def test_cli_reports_checksum_mismatches_on_stderr_and_exits_zero(
    monkeypatch, capsys
) -> None:
    import db.migrate as migrate_module
    from db.migrate import MigrationResult

    from scripts import migrate as cli

    async def fake_apply(_url, _dir):
        return MigrationResult(skipped=["001_edited.sql"], checksum_mismatches=["001_edited.sql"])

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/h")
    monkeypatch.setattr(migrate_module, "apply_migrations", fake_apply)

    assert await cli._run() == 0
    assert "001_edited.sql" in capsys.readouterr().err
