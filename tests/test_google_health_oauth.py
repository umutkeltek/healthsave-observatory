"""Google Health API OAuth helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID  # noqa: E402
from plugins.sources.google_health.oauth import (  # noqa: E402
    GOOGLE_HEALTH_PROVIDER,
    OAUTH_AUTH_URL,
    OAUTH_TOKEN_URL,
    DEFAULT_SCOPES,
    GoogleHealthClientConfig,
    build_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
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
        self.last_headers: dict[str, str] | None = None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _Response:
        self.last_url = url
        self.last_data = data
        self.last_headers = headers
        return self.response


def _config() -> GoogleHealthClientConfig:
    return GoogleHealthClientConfig(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.test/google-health/callback",
    )


def test_build_authorization_url_uses_google_oauth_endpoint_and_health_scope() -> None:
    url = build_authorization_url(_config(), state="nonce")

    assert url.startswith(f"{OAUTH_AUTH_URL}?")
    assert "response_type=code" in url
    assert "client_id=client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert DEFAULT_SCOPES[0].replace(":", "%3A").replace("/", "%2F") in url


@pytest.mark.asyncio
async def test_exchange_code_for_token_uses_google_token_endpoint() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    client = _HttpClient(
        _Response(
            200,
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "scope": " ".join(DEFAULT_SCOPES),
            },
        )
    )

    token = await exchange_code_for_token(client, _config(), code="CODE", now=now)

    assert client.last_url == OAUTH_TOKEN_URL
    assert client.last_headers == {"Accept": "application/json"}
    assert client.last_data == {
        "grant_type": "authorization_code",
        "code": "CODE",
        "redirect_uri": "https://example.test/google-health/callback",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    assert token.owner_id == DEFAULT_OWNER_ID
    assert token.provider == GOOGLE_HEALTH_PROVIDER
    assert token.access_token == "access-token"
    assert token.refresh_token == "refresh-token"
    assert token.expires_at == now + timedelta(seconds=3540)
    assert token.scopes == DEFAULT_SCOPES


@pytest.mark.asyncio
async def test_refresh_access_token_keeps_existing_refresh_token_when_google_omits_new_one() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    client = _HttpClient(
        _Response(
            200,
            {
                "access_token": "new-access-token",
                "expires_in": 1800,
                "scope": " ".join(DEFAULT_SCOPES),
            },
        )
    )

    token = await refresh_access_token(
        client,
        _config(),
        refresh_token="existing-refresh-token",
        now=now,
    )

    assert client.last_url == OAUTH_TOKEN_URL
    assert client.last_data == {
        "grant_type": "refresh_token",
        "refresh_token": "existing-refresh-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    assert token.access_token == "new-access-token"
    assert token.refresh_token == "existing-refresh-token"
    assert token.expires_at == now + timedelta(seconds=1740)
