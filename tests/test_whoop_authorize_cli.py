"""Tests for the Whoop authorize CLI's testable seam.

The interactive shell (``_interactive_main``) is not unit-tested —
it's I/O glue around :func:`run_authorize_flow`. The tests below
cover the pure-async core with recording doubles for the HTTP
client, the session, and the token store, then assert that:

  * The code exchange POSTs ``grant_type=authorization_code`` plus the
    operator-supplied code to Whoop's token endpoint.
  * The returned token is persisted via ``put_token('authorized')``.
  * The session is committed exactly once.
  * A non-200 token response surfaces as :class:`WhoopOAuthError`
    and nothing is persisted.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whoop_authorize import run_authorize_flow  # noqa: E402

from plugins.sources.whoop.oauth import WhoopClientConfig, WhoopOAuthError  # noqa: E402


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class _HttpClient:
    response: _Response
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def post(self, url, *, data=None, headers=None):
        self.calls.append({"url": url, "data": dict(data or {})})
        return self.response


@dataclass
class _Session:
    commits: int = 0

    async def execute(self, statement, params=None):
        return None

    async def commit(self):
        self.commits += 1


@dataclass
class _TokenStore:
    put_calls: list[tuple[Any, str]] = field(default_factory=list)

    async def put_token(self, session, token, *, event_kind="authorized"):
        self.put_calls.append((token, event_kind))


def _oauth_config() -> WhoopClientConfig:
    return WhoopClientConfig(client_id="cid", client_secret="csecret", redirect_uri="https://t/cb")


@pytest.mark.asyncio
async def test_run_authorize_flow_exchanges_code_persists_token_and_commits():
    http = _HttpClient(
        response=_Response(
            200,
            {
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "scope": "read:recovery offline",
                "token_type": "Bearer",
            },
        )
    )
    session = _Session()
    token_store = _TokenStore()

    token = await run_authorize_flow(
        code="abc",
        oauth_config=_oauth_config(),
        http_client=http,
        session=session,
        token_store=token_store,
    )

    # The code exchange POSTed authorization_code with our supplied code.
    assert len(http.calls) == 1
    assert http.calls[0]["data"]["grant_type"] == "authorization_code"
    assert http.calls[0]["data"]["code"] == "abc"

    # The returned token carries the access_token from Whoop.
    assert token.access_token == "AT"
    assert token.refresh_token == "RT"

    # Persistence + commit ran exactly once.
    assert len(token_store.put_calls) == 1
    stored_token, event_kind = token_store.put_calls[0]
    assert stored_token is token
    assert event_kind == "authorized"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_run_authorize_flow_raises_on_token_endpoint_error():
    http = _HttpClient(response=_Response(400, {"error": "invalid_grant"}, text="bad"))
    session = _Session()
    token_store = _TokenStore()

    with pytest.raises(WhoopOAuthError):
        await run_authorize_flow(
            code="abc",
            oauth_config=_oauth_config(),
            http_client=http,
            session=session,
            token_store=token_store,
        )

    # No persistence, no commit, on a failed exchange.
    assert token_store.put_calls == []
    assert session.commits == 0
