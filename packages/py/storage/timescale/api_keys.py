"""Participant API keys (migration 029).

One Observatory per coach or clinic, one key per participant. A participant
is an owner: the key a phone holds decides which ``owner_id`` its rows land
under. The legacy single ``API_KEY`` from ``.env`` never touches this table.

Only the SHA-256 of a key is stored. :func:`mint_api_key` returns the
plaintext exactly once; the caller prints it and forgets it.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contracts._base import DEFAULT_OWNER_ID
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from .analysis import fetch_last_ingested_at

API_KEY_SCOPES: frozenset[str] = frozenset({"ingest", "read", "admin"})
#: Keys a participant phone (or a participant's own read tool) holds. Admin
#: keys act for the primary person and are not participants.
PARTICIPANT_SCOPES: frozenset[str] = frozenset({"ingest", "read"})
MAX_LABEL_LENGTH = 64

_UNDEFINED_TABLE = "42P01"

_KEY_COLUMNS = "id, label, scope, owner_id, created_at, revoked_at"


class ApiKeyError(ValueError):
    """Deterministic refusal (bad label, scope, or a live duplicate)."""


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: UUID
    label: str
    scope: str
    owner_id: UUID
    created_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


def hash_api_key(key: str) -> str:
    """Lowercase hex SHA-256 of the exact key bytes (UTF-8)."""

    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def mint_api_key() -> str:
    """A fresh 48-hex-character key: the shape ``healthsave pair`` mints."""

    return secrets.token_hex(24)


def normalize_label(label: str) -> str:
    """Trim and validate a participant label; raise :class:`ApiKeyError`."""

    cleaned = " ".join((label or "").split())
    if not cleaned:
        raise ApiKeyError("label must not be empty")
    if len(cleaned) > MAX_LABEL_LENGTH:
        raise ApiKeyError(f"label must be at most {MAX_LABEL_LENGTH} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ApiKeyError("label must not contain control characters")
    return cleaned


def _record(row: Any) -> ApiKeyRecord | None:
    """Row -> record, or None when the row is not a well-formed key row.

    Strict on purpose: the caller makes an auth decision from this, so a row
    that does not carry a real UUID owner and a known scope is no key at all.
    """

    if row is None:
        return None
    try:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        scope = mapping["scope"]
        label = mapping["label"]
        if scope not in API_KEY_SCOPES or not isinstance(label, str):
            return None
        return ApiKeyRecord(
            id=UUID(str(mapping["id"])),
            label=label,
            scope=scope,
            owner_id=UUID(str(mapping["owner_id"])),
            created_at=mapping["created_at"],
            revoked_at=mapping["revoked_at"],
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _is_undefined_table(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) == _UNDEFINED_TABLE or (
        getattr(getattr(orig, "__cause__", None), "sqlstate", None) == _UNDEFINED_TABLE
    )


async def find_api_key(session, key_hash: str) -> ApiKeyRecord | None:
    """The key row for ``key_hash`` (active or revoked), else None.

    A database without migration 029 has no participant keys: an undefined
    table reads as "no such key". Every other database error propagates so
    the caller can answer 503 instead of guessing.
    """

    try:
        result = await session.execute(
            text(f"SELECT {_KEY_COLUMNS} FROM api_keys WHERE key_hash = :key_hash LIMIT 1"),
            {"key_hash": key_hash},
        )
    except ProgrammingError as exc:
        if _is_undefined_table(exc):
            return None
        raise
    return _record(result.first())


async def _owner_for_label(session, label: str) -> UUID | None:
    result = await session.execute(
        text(
            """
            SELECT owner_id
            FROM api_keys
            WHERE lower(label) = lower(:label)
              AND scope <> 'admin'
              AND owner_id <> CAST(:default_owner AS UUID)
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        # Never the primary person's owner: a participant named like the
        # primary person's own read key ("MCP read key") must not write into,
        # or read as, the primary person's record.
        {"label": label, "default_owner": str(DEFAULT_OWNER_ID)},
    )
    row = result.first()
    return UUID(str(row[0])) if row is not None else None


async def create_api_key(
    session,
    *,
    label: str,
    scope: str = "ingest",
    key_hash: str,
    primary: bool = False,
) -> ApiKeyRecord:
    """Store one key hash; return its record. Caller commits.

    Participant scopes reuse the owner of any earlier key with the same label
    (so a re-paired phone keeps writing into the same person's history) or
    start a new owner. Admin keys, and read keys minted with ``primary``
    (the person's own AI client), always act for the default owner.
    """

    clean_label = normalize_label(label)
    if scope not in API_KEY_SCOPES:
        raise ApiKeyError(f"scope must be one of {sorted(API_KEY_SCOPES)}")
    if primary and scope != "read":
        raise ApiKeyError("only a read key can be minted for the primary person")
    if scope == "admin" or primary:
        # A primary read key (``healthsave mcp key``) reads the primary
        # person's own record; it is not a participant and never one.
        owner_id = DEFAULT_OWNER_ID
    else:
        owner_id = await _owner_for_label(session, clean_label) or uuid4()
    try:
        result = await session.execute(
            text(
                f"""
                INSERT INTO api_keys (key_hash, label, scope, owner_id)
                VALUES (:key_hash, :label, :scope, CAST(:owner_id AS UUID))
                RETURNING {_KEY_COLUMNS}
                """
            ),
            {
                "key_hash": key_hash,
                "label": clean_label,
                "scope": scope,
                "owner_id": str(owner_id),
            },
        )
    except IntegrityError as exc:
        raise ApiKeyError(
            f"{clean_label!r} already has a live {scope} key; revoke it first"
        ) from exc
    record = _record(result.first())
    if record is None:  # pragma: no cover - RETURNING always yields the row
        raise ApiKeyError("key row was not stored")
    return record


async def revoke_label(session, label: str) -> int:
    """Revoke every live key with ``label``; return how many. Caller commits."""

    result = await session.execute(
        text(
            """
            UPDATE api_keys
            SET revoked_at = NOW()
            WHERE lower(label) = lower(:label)
              AND revoked_at IS NULL
            """
        ),
        {"label": normalize_label(label)},
    )
    return int(result.rowcount or 0)


async def list_keys(session) -> list[ApiKeyRecord]:
    """Every key row, newest first (no hashes)."""

    result = await session.execute(
        text(f"SELECT {_KEY_COLUMNS} FROM api_keys ORDER BY lower(label), created_at DESC")
    )
    return [record for row in result.all() if (record := _record(row)) is not None]


async def list_owners(session) -> list[dict[str, Any]]:
    """The default owner first, then one entry per participant owner.

    ``label`` is the newest key's label; ``active`` is whether any key of
    that owner is still live; ``scopes`` lists the live scopes. Revoked
    participants stay listed: their data stays. ``last_ingest_at`` is the
    newest canonical observation stored for that owner.
    """

    try:
        result = await session.execute(
            text(
                """
                SELECT owner_id,
                       (array_agg(label ORDER BY created_at DESC))[1] AS label,
                       min(created_at) AS created_at,
                       coalesce(
                           array_agg(DISTINCT scope) FILTER (WHERE revoked_at IS NULL),
                           ARRAY[]::text[]
                       ) AS scopes,
                       bool_or(revoked_at IS NULL) AS active
                FROM api_keys
                WHERE scope <> 'admin'
                  AND owner_id <> CAST(:default_owner AS UUID)
                GROUP BY owner_id
                ORDER BY lower((array_agg(label ORDER BY created_at DESC))[1])
                """
            ),
            {"default_owner": str(DEFAULT_OWNER_ID)},
        )
        participant_rows = [dict(row._mapping) for row in result.all()]
    except ProgrammingError as exc:
        if not _is_undefined_table(exc):
            raise
        await session.rollback()
        participant_rows = []

    owners: list[dict[str, Any]] = [
        {
            "id": str(DEFAULT_OWNER_ID),
            "label": None,
            "is_default": True,
            "active": True,
            "scopes": [],
            "created_at": None,
        }
    ]
    for row in participant_rows:
        owners.append(
            {
                "id": str(row["owner_id"]),
                "label": row["label"],
                "is_default": False,
                "active": bool(row["active"]),
                "scopes": sorted(row["scopes"] or []),
                "created_at": row["created_at"],
            }
        )
    for owner in owners:
        owner["last_ingest_at"] = await fetch_last_ingested_at(session, owner_id=UUID(owner["id"]))
    return owners


__all__ = [
    "API_KEY_SCOPES",
    "MAX_LABEL_LENGTH",
    "PARTICIPANT_SCOPES",
    "ApiKeyError",
    "ApiKeyRecord",
    "create_api_key",
    "find_api_key",
    "hash_api_key",
    "list_keys",
    "list_owners",
    "mint_api_key",
    "normalize_label",
    "revoke_label",
]
