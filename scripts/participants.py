"""Participant keys from inside the API container (migration 029).

``healthsave participants ...`` runs this with ``docker compose exec -T api
python -m scripts.participants ...`` so the key is minted, hashed and stored
by the same code the API authenticates with, and the plaintext never
appears on a command line or in the database.

Usage:
  python -m scripts.participants add LABEL [--scope ingest|read] [--primary]
  python -m scripts.participants list
  python -m scripts.participants revoke LABEL

``add`` prints ``key=``, ``owner_id=``, ``label=`` and ``scope=`` lines
once; the caller shows them to the operator and keeps nothing.

Exit codes:
  0  done
  1  DATABASE_URL missing, or ``revoke`` found no live key for the label
  2  refused: bad label/scope, or the label already has a live key of that scope
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any


def _when(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return "-"


async def _with_session(work: Callable[[Any], Awaitable[int]]) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 1
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await work(session)
    finally:
        await engine.dispose()


async def _add(session: Any, label: str, scope: str, primary: bool = False) -> int:
    from storage.timescale.api_keys import ApiKeyError, create_api_key, hash_api_key, mint_api_key

    key = mint_api_key()
    try:
        record = await create_api_key(
            session, label=label, scope=scope, key_hash=hash_api_key(key), primary=primary
        )
    except ApiKeyError as exc:
        await session.rollback()
        print(f"error: {exc}", file=sys.stderr)
        return 2
    await session.commit()
    print(f"key={key}")
    print(f"owner_id={record.owner_id}")
    print(f"label={record.label}")
    print(f"scope={record.scope}")
    return 0


async def _list(session: Any) -> int:
    from storage.timescale.api_keys import list_owners

    owners = await list_owners(session)
    participants = [owner for owner in owners if not owner["is_default"]]
    if not participants:
        print("No participants yet. Add one with: healthsave participants add NAME")
        return 0
    rows = [("NAME", "STATUS", "KEYS", "LAST DATA", "OWNER ID")]
    for owner in participants:
        rows.append(
            (
                owner["label"] or "-",
                "active" if owner["active"] else "revoked",
                ",".join(owner["scopes"]) or "-",
                _when(owner["last_ingest_at"]),
                owner["id"],
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return 0


async def _revoke(session: Any, label: str) -> int:
    from storage.timescale.api_keys import ApiKeyError, revoke_label

    try:
        revoked = await revoke_label(session, label)
    except ApiKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    await session.commit()
    if revoked == 0:
        print(f"error: no live key named {label!r}", file=sys.stderr)
        return 1
    print(f"revoked={revoked}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.participants", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="mint a key for a participant")
    add.add_argument("label")
    add.add_argument("--scope", choices=("ingest", "read"), default="ingest")
    add.add_argument(
        "--primary",
        action="store_true",
        help="read key for the primary person's own tools (healthsave mcp key); needs --scope read",
    )
    commands.add_parser("list", help="list participants")
    revoke = commands.add_parser("revoke", help="revoke every live key of a participant")
    revoke.add_argument("label")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "add":
        return asyncio.run(_with_session(lambda s: _add(s, args.label, args.scope, args.primary)))
    if args.command == "list":
        return asyncio.run(_with_session(_list))
    return asyncio.run(_with_session(lambda s: _revoke(s, args.label)))


if __name__ == "__main__":
    raise SystemExit(main())
