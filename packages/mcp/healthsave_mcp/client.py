"""The one door out of the MCP server: read-only GETs to one Observatory.

Nothing else in this package opens a connection. The client refuses any
method but GET, any path outside ``/api/v2/``, any absolute URL, and any
redirect, and it ignores proxy settings from the environment, so every byte
goes to the address in ``HEALTHSAVE_URL`` and nowhere else.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__

ENV_URL = "HEALTHSAVE_URL"
ENV_KEY = "HEALTHSAVE_API_KEY"
READ_PREFIX = "/api/v2/"
DEFAULT_TIMEOUT = 30.0


class ConfigError(ValueError):
    """The server cannot start: the address or key is missing or malformed."""


class ObservatoryError(RuntimeError):
    """The Observatory answered with an error; ``code`` is stable for callers."""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    def as_limitation(self) -> dict[str, Any]:
        return {"code": self.code, "detail": str(self)}


@dataclass(frozen=True, slots=True)
class Config:
    url: str
    api_key: str
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        url = (env.get(ENV_URL) or "").strip().rstrip("/")
        key = (env.get(ENV_KEY) or "").strip()
        if not url:
            raise ConfigError(
                f"{ENV_URL} is not set. Set it to your Observatory's API address, "
                "for example http://192.168.1.20:8000 (run `healthsave mcp` on the server)."
            )
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConfigError(f"{ENV_URL} must be an http:// or https:// address, got {url!r}.")
        if parts.username or parts.password:
            raise ConfigError(f"{ENV_URL} must not carry a user name or password.")
        if parts.query or parts.fragment or parts.path not in ("", "/"):
            raise ConfigError(
                f"{ENV_URL} is the server address only (no path), for example "
                "http://192.168.1.20:8000."
            )
        if any(ch.isspace() or ord(ch) < 32 for ch in key):
            raise ConfigError(f"{ENV_KEY} must not contain spaces or control characters.")
        return cls(url=url, api_key=key)


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else ""


class ObservatoryClient:
    """Async GET-only client bound to one Observatory address."""

    def __init__(
        self,
        config: Config,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json", "User-Agent": f"healthsave-mcp/{__version__}"}
        if config.api_key:
            headers["X-API-Key"] = config.api_key
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.url,
            headers=headers,
            timeout=config.timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        if not path.startswith(READ_PREFIX) or "://" in path or ".." in path or "//" in path:
            raise ValueError(f"refusing to read {path!r}: only {READ_PREFIX}* paths are read")
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = await self._http.request("GET", path, params=clean)
        except httpx.TimeoutException as exc:
            raise ObservatoryError(
                "timeout", f"The Observatory at {self.config.url} did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            raise ObservatoryError(
                "unreachable",
                f"Could not reach the Observatory at {self.config.url} ({type(exc).__name__}).",
            ) from exc
        status = response.status_code
        if 300 <= status < 400:
            raise ObservatoryError(
                "redirect_refused",
                f"The Observatory answered {status} with a redirect; this server only "
                f"talks to {self.config.url} and does not follow it.",
                status,
            )
        if status == 401:
            raise ObservatoryError(
                "key_rejected",
                "The Observatory did not accept the key (HTTP 401). Check HEALTHSAVE_API_KEY, "
                "or mint a new one with `healthsave mcp key --rotate` on the server.",
                status,
            )
        if status == 403:
            raise ObservatoryError(
                "key_scope",
                "This key may not read this part of the record (HTTP 403"
                + (f": {_detail(response)}" if _detail(response) else "")
                + "). A participant's read key sees that person's own readings only; "
                "findings and lab results need the key `healthsave mcp key` makes.",
                status,
            )
        if status == 404:
            raise ObservatoryError("not_found", _detail(response) or "Not found (HTTP 404).", 404)
        if status == 422:
            raise ObservatoryError(
                "rejected", _detail(response) or "The Observatory rejected the request.", 422
            )
        if status >= 500:
            raise ObservatoryError(
                "unavailable",
                f"The Observatory answered HTTP {status}"
                + (f": {_detail(response)}" if _detail(response) else "")
                + ". Is the stack up? `healthsave doctor` on the server says.",
                status,
            )
        if status >= 400:
            raise ObservatoryError("http_error", f"HTTP {status} from {path}.", status)
        try:
            return response.json()
        except ValueError as exc:
            raise ObservatoryError(
                "not_json", f"{path} did not return JSON; is {self.config.url} an Observatory?"
            ) from exc
