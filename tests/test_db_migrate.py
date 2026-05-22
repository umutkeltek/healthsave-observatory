from __future__ import annotations

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
        applied: set[str] | None = None,
        fail_on_sql: str | None = None,
    ) -> None:
        self.applied = applied or set()
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
        return [{"filename": filename} for filename in sorted(self.applied)]

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
