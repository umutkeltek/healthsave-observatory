"""One-time CLI Polar AccessLink authorization-code grant."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import secrets
import sys
import webbrowser
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "packages" / "py"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402

from plugins.sources.polar.oauth import (  # noqa: E402
    PolarClientConfig,
    build_authorization_url,
    exchange_code_for_token,
    register_user,
)


async def run_authorize_flow(
    *,
    code: str,
    oauth_config: PolarClientConfig,
    http_client,
    session,
    token_store,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    token = await exchange_code_for_token(http_client, oauth_config, code=code, owner_id=owner_id)
    await register_user(http_client, access_token=token.access_token, member_id=str(owner_id))
    await token_store.put_token(session, token, event_kind="authorized")
    await session.commit()
    return token


async def _interactive_main(owner_id: UUID = DEFAULT_OWNER_ID) -> int:  # pragma: no cover
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from storage.timescale import oauth_tokens as token_store

    try:
        oauth_config = PolarClientConfig.from_env()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(32)
    url = build_authorization_url(oauth_config, state=state)
    print("Open URL in browser, grant access, paste the 'code'")
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
    print(f"authorized Polar user x_user_id={token.metadata.get('x_user_id')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", default=str(DEFAULT_OWNER_ID))
    args = parser.parse_args(argv)
    return asyncio.run(_interactive_main(owner_id=UUID(args.owner_id)))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
