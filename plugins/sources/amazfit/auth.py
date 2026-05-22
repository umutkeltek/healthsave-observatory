"""Zepp / huami-token authentication helpers.

Pure helpers — persistence is delegated to
:mod:`storage.timescale.oauth_tokens` (same repo Whoop uses, provider
``"amazfit"``). The HTTP client is injected via Protocol so tests
substitute a recording double and exercise the parse/materialize
boundary without a network dependency.

Why MD5 of the password? The Zepp login endpoint accepts password as
an MD5 hex digest of the plaintext. This is **not** a security feature
on Zepp's side — the digest goes over TLS just like the plaintext
would — it is just the wire shape the endpoint expects. We hash at
the client-credential boundary so the encrypted-at-rest secret
material is the digest, not the cleartext.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

from . import AUTH_LOGIN_URL, PROVIDER, REGION_BASE_URLS

ENV_EMAIL = "AMAZFIT_EMAIL"
ENV_PASSWORD = "AMAZFIT_PASSWORD"
ENV_REGION = "AMAZFIT_REGION"

# Default app_token lifetime if the response omits an explicit expiry.
# Zepp app_tokens have historically lasted ~30 days; we hedge to 25
# days so the re-login fires before the token is actually rejected.
DEFAULT_TOKEN_TTL = timedelta(days=25)


class AmazfitAuthError(Exception):
    """Raised when Zepp's auth endpoints return an error or malformed payload."""


@dataclass(frozen=True, slots=True)
class AmazfitClientConfig:
    """Credentials + region the auth helpers need.

    Stored only in memory — the password never lands in the DB
    encrypted-at-rest. The persisted artifact is the app_token, not the
    password. If the app_token expires, the worker reloads
    :class:`AmazfitClientConfig` from env and runs login again.
    """

    email: str
    password: str
    region: str = "us"

    @property
    def base_url(self) -> str:
        """Region-keyed base URL for the Zepp data API.

        Unknown regions fall back to the US host rather than raising,
        matching the historical personal_stack behaviour.
        """
        return REGION_BASE_URLS.get(self.region, REGION_BASE_URLS["us"])

    @classmethod
    def from_env(cls) -> AmazfitClientConfig:
        missing = [v for v in (ENV_EMAIL, ENV_PASSWORD) if not os.environ.get(v)]
        if missing:
            raise AmazfitAuthError(f"missing required Amazfit env vars: {', '.join(missing)}")
        return cls(
            email=os.environ[ENV_EMAIL],
            password=os.environ[ENV_PASSWORD],
            region=os.environ.get(ENV_REGION, "us").lower(),
        )


class _HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class _HttpClient(Protocol):
    """Minimum POST + GET surface the auth flow needs.

    Both ``httpx.AsyncClient`` and a test double satisfy it.
    """

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = ...,
        headers: dict[str, str] | None = ...,
    ) -> _HttpResponse: ...


def md5_password(plaintext: str) -> str:
    """Return the MD5 hex digest the Zepp login endpoint expects."""
    return hashlib.md5(plaintext.encode("utf-8")).hexdigest()


async def login(
    http_client: _HttpClient,
    config: AmazfitClientConfig,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Run the two-step Zepp login flow and return a materialized OAuthToken.

    Step 1: POST email + MD5(password) to ``AUTH_LOGIN_URL`` ->
    ``token_info.login_token``.

    Step 2: GET ``<base_url>/v1/user/login/login_check?login_token=...``
    -> ``token_info.app_token``.

    The returned :class:`OAuthToken` carries:

      * ``access_token`` = the app_token used as a bearer header on
        data calls.
      * ``refresh_token`` = None (Zepp does not issue refresh tokens;
        the recovery primitive is "re-run login").
      * ``expires_at`` = now + 25 days unless the response carries an
        explicit ``expires_in``.
      * ``metadata`` = ``{"base_url": ..., "region": ..., "user_id": ...}``
        so the fetch loop can read the region-specific base_url
        without re-loading config.

    Raises :class:`AmazfitAuthError` on any non-200 status or missing
    payload field.
    """
    # Step 1 — login.
    login_response = await http_client.post(
        AUTH_LOGIN_URL,
        data={
            "client_id": "HuaMi",
            "password": md5_password(config.password),
            "account_name": config.email,
            "redirect_uri": ("https://s3-us-west-2.amazonaws.com/hm-registration/successs498.html"),
            "token": "access",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if login_response.status_code != 200:
        body = getattr(login_response, "text", "<no body>")
        raise AmazfitAuthError(f"login HTTP {login_response.status_code}: {body}")
    login_payload = _safe_json(login_response, step="login")
    token_info = login_payload.get("token_info") or {}
    login_token = token_info.get("login_token")
    if not login_token:
        raise AmazfitAuthError(f"login response missing token_info.login_token: {login_payload}")
    user_id = token_info.get("user_id") or ""

    # Step 2 — token exchange for app_token.
    exchange_response = await http_client.get(
        f"{config.base_url}/v1/user/login/login_check",
        params={"login_token": login_token},
        headers={"Accept": "application/json"},
    )
    if exchange_response.status_code != 200:
        body = getattr(exchange_response, "text", "<no body>")
        raise AmazfitAuthError(f"token exchange HTTP {exchange_response.status_code}: {body}")
    exchange_payload = _safe_json(exchange_response, step="token_exchange")
    exchange_token_info = exchange_payload.get("token_info") or {}
    app_token = exchange_token_info.get("app_token")
    if not app_token:
        raise AmazfitAuthError(
            f"token exchange response missing token_info.app_token: {exchange_payload}"
        )

    expires_at = _materialize_expires_at(exchange_token_info)
    return OAuthToken(
        owner_id=owner_id,
        provider=PROVIDER,
        access_token=app_token,
        refresh_token=None,
        expires_at=expires_at,
        scopes=(),
        metadata={
            "base_url": config.base_url,
            "region": config.region,
            "user_id": str(user_id),
        },
    )


def _safe_json(response: _HttpResponse, *, step: str) -> dict[str, Any]:
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001 — Zepp clients raise varying shapes
        raise AmazfitAuthError(f"{step} response was not JSON") from exc


def _materialize_expires_at(token_info: dict[str, Any]) -> datetime:
    """Build the expires_at timestamp from the response or fall back."""
    raw = token_info.get("expires_in") or token_info.get("ttl")
    if raw is None:
        return datetime.now(UTC) + DEFAULT_TOKEN_TTL
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return datetime.now(UTC) + DEFAULT_TOKEN_TTL
    return datetime.now(UTC) + timedelta(seconds=seconds)
