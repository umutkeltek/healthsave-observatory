"""Polar AccessLink OAuth helpers.

Polar access tokens do not expire unless revoked, so unlike Whoop this module
does not implement refresh. Registration with ``/v3/users`` is part of the
authorization flow because data calls only return exercises uploaded after the
user is registered with the client.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

POLAR_PROVIDER = "polar-accesslink"
POLAR_API_BASE = "https://www.polaraccesslink.com"
OAUTH_AUTH_URL = "https://flow.polar.com/oauth2/authorization"
OAUTH_TOKEN_URL = "https://polarremote.com/v2/oauth2/token"

ENV_CLIENT_ID = "POLAR_CLIENT_ID"
ENV_CLIENT_SECRET = "POLAR_CLIENT_SECRET"
ENV_REDIRECT_URI = "POLAR_REDIRECT_URI"


class PolarOAuthError(Exception):
    """Raised when Polar OAuth or registration returns an unusable response."""


@dataclass(frozen=True, slots=True)
class PolarClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> PolarClientConfig:
        missing = [
            name
            for name in (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REDIRECT_URI)
            if not os.environ.get(name)
        ]
        if missing:
            raise PolarOAuthError(f"missing Polar env vars: {', '.join(missing)}")
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
        json: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def _basic_auth(config: PolarClientConfig) -> str:
    raw = f"{config.client_id}:{config.client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def build_authorization_url(config: PolarClientConfig, *, state: str) -> str:
    return (
        OAUTH_AUTH_URL
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "state": state,
            }
        )
    )


async def exchange_code_for_token(
    http_client: _HttpClient,
    config: PolarClientConfig,
    *,
    code: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    response = await http_client.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
        },
        headers={"Accept": "application/json", "Authorization": _basic_auth(config)},
    )
    return _materialize_token(response, owner_id=owner_id)


async def register_user(
    http_client: _HttpClient,
    *,
    access_token: str,
    member_id: str,
) -> None:
    response = await http_client.post(
        f"{POLAR_API_BASE}/v3/users",
        json={"member-id": member_id},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    if response.status_code not in (200, 201, 409):
        body = getattr(response, "text", "<no body>")
        raise PolarOAuthError(
            f"polar user registration returned HTTP {response.status_code}: {body}"
        )


def _materialize_token(response: _HttpResponse, *, owner_id: UUID) -> OAuthToken:
    if response.status_code != 200:
        body = getattr(response, "text", "<no body>")
        raise PolarOAuthError(f"polar token endpoint returned HTTP {response.status_code}: {body}")
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise PolarOAuthError("polar token response missing access_token")
    return OAuthToken(
        owner_id=owner_id,
        provider=POLAR_PROVIDER,
        access_token=str(access_token),
        refresh_token=None,
        expires_at=None,
        scopes=(),
        metadata={"x_user_id": payload.get("x_user_id")},
    )
