"""Polar AccessLink OAuth + registration helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID  # noqa: E402
from plugins.sources.polar.oauth import (  # noqa: E402
    OAUTH_AUTH_URL,
    OAUTH_TOKEN_URL,
    POLAR_API_BASE,
    PolarClientConfig,
    build_authorization_url,
    exchange_code_for_token,
    register_user,
)


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _HttpClient:
    def __init__(self, response: _Response):
        self.response = response
        self.last_url: str | None = None
        self.last_data: dict[str, str] | None = None
        self.last_json: dict[str, str] | None = None
        self.last_headers: dict[str, str] | None = None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _Response:
        self.last_url = url
        self.last_data = data
        self.last_json = json
        self.last_headers = headers
        return self.response


def _config() -> PolarClientConfig:
    return PolarClientConfig(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="https://example.test/polar/callback",
    )


def test_build_authorization_url_uses_polar_flow_endpoint():
    url = build_authorization_url(_config(), state="nonce")

    assert url.startswith(f"{OAUTH_AUTH_URL}?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=nonce" in url


@pytest.mark.asyncio
async def test_exchange_code_uses_basic_auth_and_stores_x_user_id():
    client = _HttpClient(
        _Response(
            200,
            {
                "access_token": "AT",
                "token_type": "bearer",
                "x_user_id": 10579,
            },
        )
    )

    token = await exchange_code_for_token(client, _config(), code="CODE")

    expected_basic = base64.b64encode(b"cid:csecret").decode()
    assert client.last_url == OAUTH_TOKEN_URL
    assert client.last_headers == {
        "Accept": "application/json",
        "Authorization": f"Basic {expected_basic}",
    }
    assert client.last_data == {
        "grant_type": "authorization_code",
        "code": "CODE",
        "redirect_uri": "https://example.test/polar/callback",
    }
    assert token.owner_id == DEFAULT_OWNER_ID
    assert token.provider == "polar-accesslink"
    assert token.access_token == "AT"
    assert token.refresh_token is None
    assert token.expires_at is None
    assert token.metadata["x_user_id"] == 10579


@pytest.mark.asyncio
async def test_register_user_posts_member_id_with_bearer_token():
    client = _HttpClient(_Response(201, {"member-id": "owner-1", "polar-user-id": 10579}))

    await register_user(client, access_token="AT", member_id="owner-1")

    assert client.last_url == f"{POLAR_API_BASE}/v3/users"
    assert client.last_headers == {
        "Accept": "application/json",
        "Authorization": "Bearer AT",
        "Content-Type": "application/json",
    }
    assert client.last_json == {"member-id": "owner-1"}
