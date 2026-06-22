"""Google Health API OAuth helpers.

Google Health uses standard Google OAuth 2.0 authorization-code flow. Tokens
can expire, so this adapter mirrors Whoop's refresh path while keeping all
persistence in the shared oauth token store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

GOOGLE_HEALTH_PROVIDER = "google-health-api"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

DEFAULT_SCOPES = ("https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",)

ENV_CLIENT_ID = "GOOGLE_HEALTH_CLIENT_ID"
ENV_CLIENT_SECRET = "GOOGLE_HEALTH_CLIENT_SECRET"
ENV_REDIRECT_URI = "GOOGLE_HEALTH_REDIRECT_URI"


class GoogleHealthOAuthError(Exception):
    """Raised when Google OAuth returns an unusable response."""


@dataclass(frozen=True, slots=True)
class GoogleHealthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> GoogleHealthClientConfig:
        missing = [
            name
            for name in (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REDIRECT_URI)
            if not os.environ.get(name)
        ]
        if missing:
            raise GoogleHealthOAuthError(f"missing Google Health env vars: {', '.join(missing)}")
        return cls(
            client_id=os.environ[ENV_CLIENT_ID],
            client_secret=os.environ[ENV_CLIENT_SECRET],
            redirect_uri=os.environ[ENV_REDIRECT_URI],
        )


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class _HttpClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        data: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def build_authorization_url(
    config: GoogleHealthClientConfig,
    *,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    return f"{OAUTH_AUTH_URL}?{
        urlencode(
            {
                'response_type': 'code',
                'client_id': config.client_id,
                'redirect_uri': config.redirect_uri,
                'scope': ' '.join(scopes),
                'state': state,
                'access_type': 'offline',
                'prompt': 'consent',
            }
        )
    }"


async def exchange_code_for_token(
    http_client: _HttpClient,
    config: GoogleHealthClientConfig,
    *,
    code: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
    now: datetime | None = None,
) -> OAuthToken:
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
    return _materialize_token(response, owner_id=owner_id, now=now)


async def refresh_access_token(
    http_client: _HttpClient,
    config: GoogleHealthClientConfig,
    *,
    refresh_token: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
    now: datetime | None = None,
) -> OAuthToken:
    response = await http_client.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        headers={"Accept": "application/json"},
    )
    return _materialize_token(
        response,
        owner_id=owner_id,
        fallback_refresh_token=refresh_token,
        now=now,
    )


def _materialize_token(
    response: _HttpResponse,
    *,
    owner_id: UUID,
    fallback_refresh_token: str | None = None,
    now: datetime | None = None,
) -> OAuthToken:
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise GoogleHealthOAuthError(
            f"google health token endpoint returned HTTP {response.status_code}: {body}"
        )

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise GoogleHealthOAuthError("google health token response missing access_token")

    expires_at = None
    expires_in = payload.get("expires_in")
    if expires_in is not None:
        try:
            ttl = max(0, int(expires_in) - 60)
        except (TypeError, ValueError):
            ttl = 0
        expires_at = (now or datetime.now(UTC)) + timedelta(seconds=ttl)

    scope_raw = payload.get("scope")
    scopes = tuple(str(scope_raw).split()) if scope_raw else DEFAULT_SCOPES

    return OAuthToken(
        owner_id=owner_id,
        provider=GOOGLE_HEALTH_PROVIDER,
        access_token=str(access_token),
        refresh_token=payload.get("refresh_token") or fallback_refresh_token,
        expires_at=expires_at,
        scopes=scopes,
        metadata={},
    )
