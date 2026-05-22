"""Whoop plugin scaffold tests — manifest + entrypoint + OAuth helpers.

Mirrors ``test_plugin_apple_health.py`` for the structural checks and
adds focused tests for the OAuth-helper boundary that ships in P1.

P1 deliberately leaves :meth:`WhoopSource.ingest` as
:class:`NotImplementedError` so the worker scheduler refuses to drive
a half-built source. That contract is pinned here — any accidental
wire-up before P2 lands fails this test.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugin_sdk import (  # noqa: E402
    PluginManifest,
    Source,
    discover,
    is_sdk_compatible,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "sources" / "whoop"


def test_whoop_plugin_directory_exists():
    assert PLUGIN_DIR.is_dir(), f"Whoop plugin directory missing: {PLUGIN_DIR}"
    assert (PLUGIN_DIR / "plugin.yaml").is_file()
    assert (PLUGIN_DIR / "__init__.py").is_file()
    assert (PLUGIN_DIR / "README.md").is_file()
    assert (PLUGIN_DIR / "oauth.py").is_file()
    assert (PLUGIN_DIR / "fetch.py").is_file()


def test_whoop_manifest_parses_and_validates():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "whoop-healthsave"
    assert manifest.kind == "source"
    assert manifest.language == "python"
    assert is_sdk_compatible(manifest)


def test_whoop_manifest_declares_network_and_secrets():
    """Unlike the Apple plugin, Whoop polls outbound and needs secrets."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert manifest.permissions.network is True
    declared_secrets = set(manifest.permissions.secrets)
    must_include = {
        "WHOOP_CLIENT_ID",
        "WHOOP_CLIENT_SECRET",
        "WHOOP_REDIRECT_URI",
        "HDH_TOKEN_ENC_KEY",
    }
    missing = must_include - declared_secrets
    assert not missing, f"manifest is missing declared secrets: {missing}"


def test_whoop_manifest_emits_expected_metrics():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    declared = set(manifest.emits)
    must_include = {
        "measurement.heart_rate",
        "measurement.hrv",
        "measurement.sleep_analysis",
        "measurement.workouts",
        "measurement.recovery",
        "measurement.strain",
    }
    missing = must_include - declared
    assert not missing, f"manifest missing emits: {missing}"


def test_whoop_entrypoint_resolves_to_source_subclass():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert issubclass(cls, Source), f"{cls!r} is not a Source subclass"


def test_whoop_class_instantiates_with_manifest():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls(manifest)
    assert isinstance(instance, Source)
    assert instance.manifest is manifest


def test_whoop_plugin_discovered_under_plugins_dir():
    found = discover()
    matches = [p for p in found if p.plugin_id == "whoop-healthsave"]
    assert len(matches) == 1, f"expected exactly one whoop-healthsave plugin; found {len(matches)}"
    only = matches[0]
    assert only.kind == "source"
    assert only.plugin_dir == PLUGIN_DIR.resolve()


@pytest.mark.asyncio
async def test_whoop_ingest_is_not_implemented_in_p1():
    """The P1 scaffold MUST raise NotImplementedError on ingest.

    This pin prevents an accidental scheduler wire-up before P2 ships
    the fetch + normalization. When P2 lands this test deletes.
    """
    from plugins.sources.whoop import WhoopSource

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = WhoopSource(manifest)
    with pytest.raises(NotImplementedError):
        await plugin.ingest({})


# ──────────────────────────────────────────────────────────────────────
# OAuth helper tests — pure parsing + URL construction, no network.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _FakeResponse:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _FakeHttpClient:
    """Records the last POST so tests can assert on form data."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_data: dict[str, str] | None = None
        self.last_headers: dict[str, str] | None = None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.last_url = url
        self.last_data = data
        self.last_headers = headers
        return self._response


def _config() -> WhoopClientConfig:  # noqa: F821 (forward ref in docstring)
    from plugins.sources.whoop.oauth import WhoopClientConfig

    return WhoopClientConfig(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="https://example.test/cb",
    )


def test_build_authorization_url_includes_required_params():
    from plugins.sources.whoop.oauth import build_authorization_url

    url = build_authorization_url(_config(), state="nonce123")
    assert url.startswith("https://api.prod.whoop.com/oauth/oauth2/auth?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    # urlencoded redirect URI
    assert "redirect_uri=https%3A%2F%2Fexample.test%2Fcb" in url
    assert "scope=" in url
    assert "offline" in url  # offline scope is mandatory for refresh tokens
    assert "state=nonce123" in url


@pytest.mark.asyncio
async def test_exchange_code_for_token_materializes_oauth_token():
    from plugins.sources.whoop.oauth import exchange_code_for_token

    client = _FakeHttpClient(
        _FakeResponse(
            status_code=200,
            payload={
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "scope": "read:recovery read:sleep offline",
                "token_type": "Bearer",
            },
        )
    )
    token = await exchange_code_for_token(client, _config(), code="abc")

    assert token.access_token == "AT"
    assert token.refresh_token == "RT"
    assert token.expires_at is not None
    assert "read:recovery" in token.scopes
    assert "offline" in token.scopes
    assert token.metadata == {"token_type": "Bearer"}

    assert client.last_url == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert client.last_data is not None
    assert client.last_data["grant_type"] == "authorization_code"
    assert client.last_data["code"] == "abc"


@pytest.mark.asyncio
async def test_refresh_access_token_uses_refresh_grant():
    from plugins.sources.whoop.oauth import refresh_access_token

    client = _FakeHttpClient(
        _FakeResponse(
            status_code=200,
            payload={
                "access_token": "AT2",
                "refresh_token": "RT2",
                "expires_in": 3600,
                "scope": "read:recovery offline",
                "token_type": "Bearer",
            },
        )
    )
    token = await refresh_access_token(client, _config(), refresh_token="RT1")

    assert token.access_token == "AT2"
    assert token.refresh_token == "RT2"
    assert client.last_data is not None
    assert client.last_data["grant_type"] == "refresh_token"
    assert client.last_data["refresh_token"] == "RT1"


@pytest.mark.asyncio
async def test_token_endpoint_error_status_raises():
    from plugins.sources.whoop.oauth import WhoopOAuthError, exchange_code_for_token

    client = _FakeHttpClient(
        _FakeResponse(status_code=400, payload={"error": "invalid_grant"}, text="bad")
    )
    with pytest.raises(WhoopOAuthError):
        await exchange_code_for_token(client, _config(), code="abc")


@pytest.mark.asyncio
async def test_missing_access_token_in_response_raises():
    from plugins.sources.whoop.oauth import WhoopOAuthError, exchange_code_for_token

    client = _FakeHttpClient(_FakeResponse(status_code=200, payload={"expires_in": 3600}))
    with pytest.raises(WhoopOAuthError):
        await exchange_code_for_token(client, _config(), code="abc")
