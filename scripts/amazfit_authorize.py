"""One-time CLI for importing an externally-acquired Zepp app_token.

H-cli (mirrors Whoop's dfffcac in the chain). The Zepp v2/client/login
flow is dead as of 2026-05-22; this CLI replaces interactive
password-login with operator-supplied token import.

Two acquisition modes:

  1. ``--from-huami-token-stdout <file>`` — operator runs the
     external ``huami-token`` PyPI CLI once::

         pipx install huami-token
         huami-token --method amazfit -e <email> -p <pw> --no_logout > zepp.txt

     and pipes the output to us. We parse out ``app_token=<value>``
     plus the ``User id: <digits>`` line and persist via the same
     ``oauth_tokens`` repo Whoop uses (provider='amazfit',
     event_kind='authorized').

  2. ``--from-token <T> --user-id <U> --region <R>`` — manual mode
     for the proxy-capture path (Proxyman, Charles, mitmproxy
     against the Zepp iOS app). Values come from a captured
     ``apptoken`` request header + a numeric user_id from the URL
     path + a region the operator selects.

Idempotency: re-running overwrites the stored row (UPSERT on the
unique (owner_id, provider) constraint) and adds a new
``authorized`` audit event. Use this to refresh after the ~25-day
token TTL elapses (re-run huami-token, then re-run this CLI).

Anti: the script NEVER prints the app_token value to stdout or
stderr — only its length, expiry, and user_id. The interactive
``main()`` is not unit-tested (I/O glue); ``run_authorize_flow``
is the testable seam.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

from plugins.sources.amazfit.auth import (
    AmazfitAuthError,
    token_from_app_token_string,
    token_from_huami_token_output,
)


class _Session(Protocol):
    async def execute(self, statement: Any, params: Any = ...) -> Any: ...
    async def commit(self) -> None: ...


class _TokenStore(Protocol):
    async def put_token(
        self, session: _Session, token: OAuthToken, *, event_kind: str = "authorized"
    ) -> None: ...


async def run_authorize_flow(
    *,
    token: OAuthToken,
    session: _Session,
    token_store: _TokenStore,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Persist a pre-materialized token via the token store. Returns the token.

    Pure async — no env access, no stdin, no file I/O. The interactive
    wrapper materializes the token then calls this; tests substitute
    recording doubles.
    """
    await token_store.put_token(session, token, event_kind="authorized")
    await session.commit()
    return token


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """argparse surface — exported for tests."""
    parser = argparse.ArgumentParser(
        description="Import an externally-acquired Zepp app_token into the datahub.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--from-huami-token-stdout",
        type=Path,
        metavar="FILE",
        help=(
            "Path to a file containing huami-token --no_logout stdout "
            "(parsed for app_token + user_id)."
        ),
    )
    src.add_argument(
        "--from-token",
        type=str,
        metavar="TOKEN",
        help="Raw app_token value (use with --user-id and --region).",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="Numeric Zepp user_id (required with --from-token).",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us",
        choices=["us", "eu", "cn"],
        help="Zepp data API region (default: us).",
    )
    return parser.parse_args(argv)


def materialize_token_from_args(args: argparse.Namespace) -> OAuthToken:
    """Translate CLI args into an OAuthToken via the auth helpers.

    Raises :class:`AmazfitAuthError` on missing / malformed input so the
    interactive shell can surface a clean exit code.
    """
    if args.from_huami_token_stdout is not None:
        try:
            text = Path(args.from_huami_token_stdout).read_text(encoding="utf-8")
        except OSError as e:
            raise AmazfitAuthError(f"could not read {args.from_huami_token_stdout}: {e}") from e
        return token_from_huami_token_output(text, region=args.region)

    if not args.user_id:
        raise AmazfitAuthError("--from-token requires --user-id")
    return token_from_app_token_string(
        access_token=args.from_token,
        user_id=args.user_id,
        region=args.region,
    )


async def _interactive_main(argv: list[str] | None = None) -> int:  # pragma: no cover
    """Interactive shell: parse args, materialize token, persist."""
    import httpx  # noqa: F401 — kept for symmetry with Whoop CLI even though unused here
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale import oauth_tokens as token_store

    try:
        args = parse_args(argv)
        token = materialize_token_from_args(args)
    except (AmazfitAuthError, SystemExit) as e:
        # argparse raises SystemExit on bad args; let it propagate
        # via its own message. AmazfitAuthError prints a clean line.
        if isinstance(e, AmazfitAuthError):
            print(f"error: {e}", file=sys.stderr)
            return 1
        raise

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 1

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        stored = await run_authorize_flow(token=token, session=session, token_store=token_store)

    await engine.dispose()
    print(
        f"OK — stored amazfit token for user_id={stored.metadata.get('user_id')} "
        f"region={stored.metadata.get('region')} "
        f"app_token_len={len(stored.access_token)} "
        f"expires_at={stored.expires_at.isoformat() if stored.expires_at else 'n/a'}"
    )
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(asyncio.run(_interactive_main()))


if __name__ == "__main__":  # pragma: no cover
    main()
