"""Whoop OAuth 2.0 helpers — authorization-code flow + refresh.

Pure helpers. Persistence is delegated to
:mod:`storage.timescale.oauth_tokens` so the same code path stores
tokens for any future provider without each plugin reinventing
encryption or audit-trail mechanics.

The HTTP client is injected (``httpx.AsyncClient``-shaped) so tests
substitute a recording double and exercise the parse + materialize
boundary without a network dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

from . import DEFAULT_SCOPES, OAUTH_AUTH_URL, OAUTH_TOKEN_URL, PROVIDER

ENV_CLIENT_ID = "WHOOP_CLIENT_ID"
ENV_CLIENT_SECRET = "WHOOP_CLIENT_SECRET"
ENV_REDIRECT_URI = "WHOOP_REDIRECT_URI"


class WhoopOAuthError(Exception):
    """Raised when Whoop's OAuth endpoint returns an error or malformed payload."""


@dataclass(frozen=True, slots=True)
class WhoopClientConfig:
    """Client credentials + redirect URI registered with Whoop."""

    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> WhoopClientConfig:
        missing = [
            v for v in (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REDIRECT_URI) if not os.environ.get(v)
        ]
        if missing:
            raise WhoopOAuthError(f"missing required Whoop env vars: {', '.join(missing)}")
        return cls(
            client_id=os.environ[ENV_CLIENT_ID],
            client_secret=os.environ[ENV_CLIENT_SECRET],
            redirect_uri=os.environ[ENV_REDIRECT_URI],
        )


class _HttpResponse(Protocol):
    """Minimal contract the OAuth helpers need from an HTTP response.

    Both ``httpx.Response`` and ``requests.Response`` satisfy it; tests
    use a small dataclass that satisfies it too.
    """

    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class _HttpClient(Protocol):
    """Minimal POST surface so callers can pass an httpx.AsyncClient
    or a test double interchangeably.
    """

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def build_authorization_url(
    config: WhoopClientConfig,
    *,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """Return the URL the user opens in a browser to grant authorization.

    The caller supplies ``state`` — a CSRF nonce that MUST be stored
    server-side and verified on the callback. Whoop redirects to
    ``redirect_uri`` with ``?code=...&state=...`` after the grant.
    """
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{OAUTH_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    http_client: _HttpClient,
    config: WhoopClientConfig,
    *,
    code: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """POST to the token endpoint with the authorization code.

    Returns a materialized :class:`OAuthToken` ready to persist via
    :func:`storage.timescale.oauth_tokens.put_token` with
    ``event_kind="authorized"``.
    """
    response = await http_client.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        headers={"Accept": "application/json"},
    )
    return _materialize_token(response, owner_id=owner_id)


async def refresh_access_token(
    http_client: _HttpClient,
    config: WhoopClientConfig,
    *,
    refresh_token: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """POST to the token endpoint with ``grant_type=refresh_token``.

    Whoop's contract: a successful refresh invalidates the previous
    refresh_token. The new pair MUST be persisted atomically (via
    ``put_token`` with ``event_kind="refreshed"``) — never store the
    response partially.
    """
    response = await http_client.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": " ".join(DEFAULT_SCOPES),
        },
        headers={"Accept": "application/json"},
    )
    return _materialize_token(response, owner_id=owner_id)


def _materialize_token(response: _HttpResponse, *, owner_id: UUID) -> OAuthToken:
    """Parse a Whoop token response into an :class:`OAuthToken` or raise."""
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise WhoopOAuthError(f"whoop token endpoint returned HTTP {response.status_code}: {body}")
    payload = response.json()
    if "access_token" not in payload:
        raise WhoopOAuthError(f"whoop response missing access_token: {payload}")
    expires_in = int(payload.get("expires_in", 0))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in) if expires_in else None
    scope_str = payload.get("scope", "")
    scopes = tuple(s for s in scope_str.split(" ") if s) if scope_str else DEFAULT_SCOPES
    return OAuthToken(
        owner_id=owner_id,
        provider=PROVIDER,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scopes=scopes,
        metadata={"token_type": payload.get("token_type", "Bearer")},
    )
