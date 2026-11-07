"""Participant API key storage (migration 029) — DB-free."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from contracts._base import DEFAULT_OWNER_ID
from sqlalchemy.exc import IntegrityError, ProgrammingError
from storage.timescale import api_keys
from storage.timescale.api_keys import (
    ApiKeyError,
    create_api_key,
    find_api_key,
    hash_api_key,
    list_owners,
    mint_api_key,
    normalize_label,
    revoke_label,
)

MIGRATION = Path(__file__).resolve().parents[1] / "db" / "migrations" / "029_api_keys.sql"
OWNER = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")


class _Result:
    def __init__(self, row=None, rows=None, rowcount=0):
        self.row = row
        self.rows = rows if rows is not None else ([] if row is None else [row])
        self.rowcount = rowcount

    def first(self):
        return self.row

    def all(self):
        return self.rows

    def fetchone(self):
        return self.row


class _Session:
    """Answers each execute with the next scripted result (or raises it)."""

    def __init__(self, results):
        self.results = iter(results)
        self.calls: list[tuple[str, dict]] = []
        self.rolled_back = False

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result

    async def rollback(self):
        self.rolled_back = True


def _key_row(**over):
    values = {
        "id": uuid4(),
        "label": "Alice",
        "scope": "ingest",
        "owner_id": OWNER,
        "created_at": datetime(2026, 11, 2, tzinfo=UTC),
        "revoked_at": None,
    }
    values.update(over)
    return SimpleNamespace(_mapping=values)


def _undefined_table() -> ProgrammingError:
    return ProgrammingError("SELECT", {}, SimpleNamespace(sqlstate="42P01"))


def test_hash_is_lowercase_sha256_hex_of_exact_bytes() -> None:
    digest = hash_api_key("abc")
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert hash_api_key("abc ") != digest


def test_minted_key_has_pair_shape_and_is_fresh() -> None:
    first, second = mint_api_key(), mint_api_key()
    assert re.fullmatch(r"[0-9a-f]{48}", first)
    assert first != second


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Alice   Smith ", "Alice Smith"), ("Çağla", "Çağla"), ("a" * 64, "a" * 64)],
)
def test_label_normalization(raw: str, expected: str) -> None:
    assert normalize_label(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "a" * 65, "tab\x07bell"])
def test_label_rejections_are_deterministic(raw: str) -> None:
    with pytest.raises(ApiKeyError):
        normalize_label(raw)


async def test_find_returns_typed_record_by_hash() -> None:
    session = _Session([_Result(row=_key_row())])
    record = await find_api_key(session, "f" * 64)
    assert record is not None
    assert record.owner_id == OWNER and record.scope == "ingest" and not record.revoked
    sql, params = session.calls[0]
    assert "FROM api_keys WHERE key_hash = :key_hash" in sql
    assert params == {"key_hash": "f" * 64}


async def test_find_reports_revoked_rows_so_auth_can_refuse_them() -> None:
    session = _Session([_Result(row=_key_row(revoked_at=datetime(2026, 11, 2, tzinfo=UTC)))])
    record = await find_api_key(session, "f" * 64)
    assert record is not None and record.revoked


async def test_find_unknown_hash_is_none() -> None:
    assert await find_api_key(_Session([_Result()]), "0" * 64) is None


async def test_find_treats_a_missing_table_as_no_keys() -> None:
    assert await find_api_key(_Session([_undefined_table()]), "0" * 64) is None


async def test_find_propagates_other_database_errors() -> None:
    other = ProgrammingError("SELECT", {}, SimpleNamespace(sqlstate="42601"))
    with pytest.raises(ProgrammingError):
        await find_api_key(_Session([other]), "0" * 64)


@pytest.mark.parametrize(
    "bad",
    [
        {"scope": "superuser"},
        {"owner_id": "not-a-uuid"},
        {"label": None},
    ],
)
async def test_find_refuses_malformed_rows(bad) -> None:
    assert await find_api_key(_Session([_Result(row=_key_row(**bad))]), "0" * 64) is None


async def test_create_reuses_the_owner_of_an_earlier_key_with_the_same_label() -> None:
    session = _Session([_Result(row=(OWNER,)), _Result(row=_key_row())])
    record = await create_api_key(session, label=" Alice ", scope="ingest", key_hash="a" * 64)
    assert record.owner_id == OWNER
    lookup_sql, lookup_params = session.calls[0]
    assert "lower(label) = lower(:label)" in lookup_sql
    assert lookup_params == {"label": "Alice"}
    insert_sql, insert_params = session.calls[1]
    assert insert_sql.startswith("INSERT INTO api_keys")
    assert insert_params["owner_id"] == str(OWNER)
    assert insert_params["key_hash"] == "a" * 64
    assert "key" not in insert_params  # only the hash is ever stored


async def test_create_starts_a_new_owner_for_a_new_label() -> None:
    session = _Session([_Result(), _Result(row=_key_row(owner_id=uuid4(), label="Bob"))])
    await create_api_key(session, label="Bob", key_hash="b" * 64)
    owner = UUID(session.calls[1][1]["owner_id"])
    assert owner not in (OWNER, DEFAULT_OWNER_ID)


async def test_admin_keys_always_act_for_the_default_owner() -> None:
    session = _Session([_Result(row=_key_row(scope="admin", owner_id=DEFAULT_OWNER_ID))])
    await create_api_key(session, label="web", scope="admin", key_hash="c" * 64)
    assert session.calls[0][1]["owner_id"] == str(DEFAULT_OWNER_ID)


async def test_primary_read_key_acts_for_the_default_owner_without_a_label_lookup() -> None:
    # healthsave mcp key: the person's own AI client reads their own record.
    session = _Session([_Result(row=_key_row(scope="read", owner_id=DEFAULT_OWNER_ID))])
    record = await create_api_key(
        session, label="MCP read key", scope="read", key_hash="f" * 64, primary=True
    )
    assert record.owner_id == DEFAULT_OWNER_ID
    assert len(session.calls) == 1  # no participant owner reused or started
    insert_sql, insert_params = session.calls[0]
    assert insert_sql.startswith("INSERT INTO api_keys")
    assert insert_params["owner_id"] == str(DEFAULT_OWNER_ID)
    assert insert_params["scope"] == "read"


@pytest.mark.parametrize("scope", ["ingest", "admin"])
async def test_primary_is_for_read_keys_only(scope) -> None:
    with pytest.raises(ApiKeyError, match="only a read key"):
        await create_api_key(
            _Session([]), label="MCP read key", scope=scope, key_hash="f" * 64, primary=True
        )


async def test_create_live_duplicate_is_a_deterministic_refusal() -> None:
    duplicate = IntegrityError("INSERT", {}, Exception("uq_api_keys_live_label_scope"))
    session = _Session([_Result(row=(OWNER,)), duplicate])
    with pytest.raises(ApiKeyError, match="already has a live ingest key"):
        await create_api_key(session, label="Alice", key_hash="d" * 64)


async def test_create_rejects_unknown_scope() -> None:
    with pytest.raises(ApiKeyError):
        await create_api_key(_Session([]), label="Alice", scope="root", key_hash="e" * 64)


async def test_revoke_marks_every_live_key_of_the_label() -> None:
    session = _Session([_Result(rowcount=2)])
    assert await revoke_label(session, "alice") == 2
    sql, params = session.calls[0]
    assert "SET revoked_at = NOW()" in sql and "revoked_at IS NULL" in sql
    assert params == {"label": "alice"}


async def test_list_owners_puts_the_default_owner_first(monkeypatch) -> None:
    seen: list[UUID] = []

    async def _last(session, *, owner_id):
        seen.append(owner_id)
        return datetime(2026, 11, 1, tzinfo=UTC) if owner_id == OWNER else None

    monkeypatch.setattr(api_keys, "fetch_last_ingested_at", _last)
    row = SimpleNamespace(
        _mapping={
            "owner_id": OWNER,
            "label": "Alice",
            "created_at": None,
            "scopes": ["ingest"],
            "active": True,
        }
    )
    owners = await list_owners(_Session([_Result(rows=[row])]))
    assert [owner["is_default"] for owner in owners] == [True, False]
    assert owners[0]["id"] == str(DEFAULT_OWNER_ID) and owners[0]["label"] is None
    assert owners[1] == {
        "id": str(OWNER),
        "label": "Alice",
        "is_default": False,
        "active": True,
        "scopes": ["ingest"],
        "created_at": None,
        "last_ingest_at": datetime(2026, 11, 1, tzinfo=UTC),
    }
    assert seen == [DEFAULT_OWNER_ID, OWNER]


async def test_list_owners_without_the_table_is_just_the_default_owner(monkeypatch) -> None:
    async def _last(session, *, owner_id):
        return None

    monkeypatch.setattr(api_keys, "fetch_last_ingested_at", _last)
    session = _Session([_undefined_table()])
    owners = await list_owners(session)
    assert [owner["id"] for owner in owners] == [str(DEFAULT_OWNER_ID)]
    assert session.rolled_back


def test_migration_is_additive_and_stores_only_hashes() -> None:
    sql = MIGRATION.read_text()
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ).upper()
    for forbidden in ("DROP ", "ALTER TABLE", "RENAME", "DELETE ", "TRUNCATE"):
        assert forbidden not in statements
    assert "CREATE TABLE IF NOT EXISTS api_keys" in sql
    assert "key_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "uq_api_keys_key_hash" in sql
    assert re.search(r"\bkey\s+TEXT\b", sql) is None  # no plaintext column
