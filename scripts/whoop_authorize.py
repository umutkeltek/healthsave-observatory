"""One-time CLI for the Whoop authorization-code grant.

Pattern:

  1. Operator runs ``python scripts/whoop_authorize.py``.
  2. Script prints the authorize URL (built from WHOOP_CLIENT_ID +
     WHOOP_REDIRECT_URI + an opaque CSRF state). It also tries to open
     a browser — best-effort; falls back silently if not available.
  3. Operator approves at Whoop, gets redirected to
     ``WHOOP_REDIRECT_URI?code=<X>&state=<Y>``.
  4. Operator pastes the ``code`` value from the redirect URL into
     the script. ``state`` is not re-verified across script invocations
     since this is a single-process bootstrap; the CSRF token is
     defense-in-depth against the URL leaking to a referer log, not
     against a script-internal race.
  5. Script exchanges the code for a token and persists it via the
     :mod:`storage.timescale.oauth_tokens` repo with
     ``event_kind='authorized'``.

Idempotency: re-running the script overwrites the stored token row
(via UPSERT on the ``(owner_id, provider)`` unique constraint) and
adds a new ``authorized`` audit event. Use that to re-bind a Whoop
account after a refresh-token loss.

The interactive ``main()`` is not unit-tested — it's just I/O glue.
:func:`run_authorize_flow` is the testable seam.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import sys
import webbrowser
from typing import Any, Protocol
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

from plugins.sources.whoop.oauth import (
    WhoopClientConfig,
    build_authorization_url,
    exchange_code_for_token,
)


class _HttpClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        headers: dict[str, str] | None = ...,
    ) -> Any: ...


class _Session(Protocol):
    async def execute(self, statement: Any, params: Any = ...) -> Any: ...
    async def commit(self) -> None: ...


class _TokenStore(Protocol):
    async def put_token(
        self, session: _Session, token: OAuthToken, *, event_kind: str = "authorized"
    ) -> None: ...


async def run_authorize_flow(
    *,
    code: str,
    oauth_config: WhoopClientConfig,
    http_client: _HttpClient,
    session: _Session,
    token_store: _TokenStore,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Exchange ``code`` for a token and persist it. Returns the token.

    Pure async — no env access, no stdin, no browser. The interactive
    wrapper supplies its own ``http_client`` / ``session`` /
    ``token_store``; tests substitute recording doubles.
    """
    token = await exchange_code_for_token(http_client, oauth_config, code=code, owner_id=owner_id)
    await token_store.put_token(session, token, event_kind="authorized")
    await session.commit()
    return token


async def _interactive_main(owner_id: UUID = DEFAULT_OWNER_ID) -> int:  # pragma: no cover
    """The interactive shell: loads env, prints URL, reads code, runs the flow."""
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale import oauth_tokens as token_store

    try:
        oauth_config = WhoopClientConfig.from_env()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(32)
    url = build_authorization_url(oauth_config, state=state)

    print("Open this URL in a browser, grant access, then paste the 'code'")
    print("query parameter from the redirect URL below:")
    print()
    print(f"  {url}")
    print()
    with contextlib.suppress(Exception):
        webbrowser.open(url)

    code = input("code: ").strip()
    if not code:
        print("(no code provided; aborting)", file=sys.stderr)
        return 1

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 1

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=30.0) as http, session_factory() as session:
        token = await run_authorize_flow(
            code=code,
            oauth_config=oauth_config,
            http_client=http,
            session=session,
            token_store=token_store,
            owner_id=owner_id,
        )

    await engine.dispose()
    print(
        f"stored Whoop token for owner={owner_id} "
        f"(expires_at={token.expires_at.isoformat() if token.expires_at else 'n/a'})"
    )
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(asyncio.run(_interactive_main()))


if __name__ == "__main__":  # pragma: no cover
    main()
