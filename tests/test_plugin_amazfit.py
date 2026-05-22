"""Amazfit plugin scaffold tests — manifest + entrypoint + auth helpers.

Mirrors ``test_plugin_whoop.py``: pin manifest validity, entrypoint
resolution, scaffold contract, and the OAuth-helper surface.

The P6-a NotImplementedError pin on ``ingest`` ensures the worker
scheduler can't accidentally drive a half-built source. The test
deletes when P6-d lands the fetch + normalize + write loop.

Auth helper tests cover:

  * AmazfitClientConfig.from_env reads + region default + missing-var
    error.
  * md5_password produces the exact wire-format Zepp expects (lower-
    case hex digest).
  * login() POSTs MD5(password) and account_name to the right URL,
    then GETs the token exchange against the region-correct host,
    and materialises an OAuthToken with provider=amazfit + metadata.
  * login() raises AmazfitAuthError on non-200 / missing field /
    non-JSON response.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "py"))

from plugin_sdk import (  # noqa: E402
    PluginManifest,
    Source,
    discover,
    is_sdk_compatible,
    load_manifest,
)

from plugins.sources.amazfit import PROVIDER, AmazfitSource  # noqa: E402

PLUGIN_DIR = ROOT / "plugins" / "sources" / "amazfit"


# ─── manifest + scaffold ────────────────────────────────────────────────


def test_amazfit_plugin_directory_exists():
    assert PLUGIN_DIR.is_dir()
    for name in ("plugin.yaml", "__init__.py", "auth.py", "fetch.py", "normalize.py", "README.md"):
        assert (PLUGIN_DIR / name).is_file(), f"{name} missing"


def test_amazfit_manifest_parses_and_validates():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "amazfit-zepp"
    assert manifest.kind == "source"
    assert manifest.language == "python"
    assert is_sdk_compatible(manifest)


def test_amazfit_manifest_declares_network_and_secrets():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert manifest.permissions.network is True
    declared = set(manifest.permissions.secrets)
    must_include = {
        "AMAZFIT_EMAIL",
        "AMAZFIT_PASSWORD",
        "AMAZFIT_REGION",
        "HDH_TOKEN_ENC_KEY",
    }
    missing = must_include - declared
    assert not missing, f"manifest missing secrets: {missing}"


def test_amazfit_manifest_emits_expected_metrics():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    declared = set(manifest.emits)
    must_include = {
        "measurement.heart_rate",
        "measurement.blood_oxygen",
        "measurement.sleep_analysis",
        "measurement.stress",
        "measurement.daily_activity",
    }
    missing = must_include - declared
    assert not missing, f"manifest missing emits: {missing}"


def test_amazfit_entrypoint_resolves_to_source_subclass():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert issubclass(cls, Source)


def test_amazfit_plugin_discovered_under_plugins_dir():
    found = discover()
    matches = [p for p in found if p.plugin_id == "amazfit-zepp"]
    assert len(matches) == 1
    only = matches[0]
    assert only.kind == "source"
    assert only.plugin_dir == PLUGIN_DIR.resolve()


@pytest.mark.asyncio
async def test_amazfit_ingest_is_not_implemented_in_p6a():
    """P6-a pin: ingest raises NotImplementedError until P6-d lands
    the real fetch/normalize/write loop. Test deletes at P6-d.
    """
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AmazfitSource(manifest)
    with pytest.raises(NotImplementedError):
        await plugin.ingest({})


# ─── AmazfitClientConfig ────────────────────────────────────────────────


def test_amazfit_config_from_env_reads_credentials_and_region(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    monkeypatch.setenv("AMAZFIT_EMAIL", "u@example.com")
    monkeypatch.setenv("AMAZFIT_PASSWORD", "pw")
    monkeypatch.setenv("AMAZFIT_REGION", "eu")

    config = AmazfitClientConfig.from_env()
    assert config.email == "u@example.com"
    assert config.password == "pw"
    assert config.region == "eu"
    assert config.base_url == "https://api-mifit-de.huami.com"


def test_amazfit_config_defaults_region_to_us(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    monkeypatch.setenv("AMAZFIT_EMAIL", "u@example.com")
    monkeypatch.setenv("AMAZFIT_PASSWORD", "pw")
    monkeypatch.delenv("AMAZFIT_REGION", raising=False)

    config = AmazfitClientConfig.from_env()
    assert config.region == "us"
    assert config.base_url == "https://api-mifit-us2.huami.com"


def test_amazfit_config_unknown_region_falls_back_to_us():
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    config = AmazfitClientConfig(email="u@e", password="pw", region="atlantis")
    assert config.base_url == "https://api-mifit-us2.huami.com"


def test_amazfit_config_missing_env_raises(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitAuthError, AmazfitClientConfig

    for var in ("AMAZFIT_EMAIL", "AMAZFIT_PASSWORD", "AMAZFIT_REGION"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(AmazfitAuthError):
        AmazfitClientConfig.from_env()


def test_md5_password_matches_wire_format():
    from plugins.sources.amazfit.auth import md5_password

    # Known MD5 — "password" -> 5f4dcc3b5aa765d61d8327deb882cf99
    assert md5_password("password") == "5f4dcc3b5aa765d61d8327deb882cf99"


# ─── login() ────────────────────────────────────────────────────────────


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""
    _raise_on_json: bool = False

    def json(self) -> dict[str, Any]:
        if self._raise_on_json:
            raise ValueError("not json")
        return self.payload


@dataclass
class _RecordingHttp:
    login_response: _Response
    exchange_response: _Response | None = None
    post_calls: list[dict[str, Any]] = field(default_factory=list)
    get_calls: list[dict[str, Any]] = field(default_factory=list)

    async def post(self, url, *, data=None, headers=None):
        self.post_calls.append({"url": url, "data": dict(data or {})})
        return self.login_response

    async def get(self, url, *, params=None, headers=None):
        self.get_calls.append({"url": url, "params": dict(params or {})})
        if self.exchange_response is None:
            raise AssertionError("no canned exchange response")
        return self.exchange_response


def _config() -> object:  # noqa: F821
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    return AmazfitClientConfig(email="u@e", password="pw", region="us")


@pytest.mark.asyncio
async def test_login_runs_two_step_flow_and_materializes_oauth_token():
    from plugins.sources.amazfit.auth import login

    http = _RecordingHttp(
        login_response=_Response(
            status_code=200,
            payload={
                "token_info": {"login_token": "LT1", "user_id": "42"},
            },
        ),
        exchange_response=_Response(
            status_code=200,
            payload={"token_info": {"app_token": "AT1", "expires_in": 86400}},
        ),
    )

    token = await login(http, _config())

    assert token.provider == PROVIDER
    assert token.access_token == "AT1"
    assert token.refresh_token is None
    assert token.expires_at is not None
    assert token.metadata["base_url"] == "https://api-mifit-us2.huami.com"
    assert token.metadata["region"] == "us"
    assert token.metadata["user_id"] == "42"

    # Step 1 POST sent md5(pw) as password, not plaintext.
    [post] = http.post_calls
    assert post["url"].endswith("/v2/client/login")
    # MD5 of "pw" is 8fe4c11451281c094a6578e6ddbf5eed
    assert post["data"]["password"] == "8fe4c11451281c094a6578e6ddbf5eed"
    assert post["data"]["account_name"] == "u@e"

    # Step 2 GET hit the region-correct host with the login_token.
    [get] = http.get_calls
    assert get["url"].startswith("https://api-mifit-us2.huami.com")
    assert get["params"]["login_token"] == "LT1"


@pytest.mark.asyncio
async def test_login_falls_back_to_default_ttl_when_response_omits_expires():
    from plugins.sources.amazfit.auth import DEFAULT_TOKEN_TTL, login

    http = _RecordingHttp(
        login_response=_Response(
            status_code=200,
            payload={"token_info": {"login_token": "LT"}},
        ),
        exchange_response=_Response(
            status_code=200,
            payload={"token_info": {"app_token": "AT"}},
        ),
    )
    from datetime import UTC, datetime

    before = datetime.now(UTC)
    token = await login(http, _config())
    after = datetime.now(UTC)

    assert token.expires_at is not None
    # Within ~5 seconds of (now + 25 days) on either side of the call.
    expected_low = before + DEFAULT_TOKEN_TTL
    expected_high = after + DEFAULT_TOKEN_TTL
    assert expected_low <= token.expires_at <= expected_high


@pytest.mark.asyncio
async def test_login_raises_on_login_endpoint_error():
    from plugins.sources.amazfit.auth import AmazfitAuthError, login

    http = _RecordingHttp(
        login_response=_Response(status_code=401, payload={}, text="bad creds"),
    )
    with pytest.raises(AmazfitAuthError):
        await login(http, _config())


@pytest.mark.asyncio
async def test_login_raises_on_token_exchange_failure():
    from plugins.sources.amazfit.auth import AmazfitAuthError, login

    http = _RecordingHttp(
        login_response=_Response(
            status_code=200,
            payload={"token_info": {"login_token": "LT"}},
        ),
        exchange_response=_Response(status_code=500, payload={}, text="oops"),
    )
    with pytest.raises(AmazfitAuthError):
        await login(http, _config())


@pytest.mark.asyncio
async def test_login_raises_when_login_token_missing():
    from plugins.sources.amazfit.auth import AmazfitAuthError, login

    http = _RecordingHttp(
        login_response=_Response(status_code=200, payload={"token_info": {}}),
    )
    with pytest.raises(AmazfitAuthError):
        await login(http, _config())


@pytest.mark.asyncio
async def test_login_raises_when_app_token_missing():
    from plugins.sources.amazfit.auth import AmazfitAuthError, login

    http = _RecordingHttp(
        login_response=_Response(
            status_code=200,
            payload={"token_info": {"login_token": "LT"}},
        ),
        exchange_response=_Response(
            status_code=200,
            payload={"token_info": {"not_app_token": "wrong"}},
        ),
    )
    with pytest.raises(AmazfitAuthError):
        await login(http, _config())


@pytest.mark.asyncio
async def test_login_raises_when_response_is_not_json():
    from plugins.sources.amazfit.auth import AmazfitAuthError, login

    http = _RecordingHttp(
        login_response=_Response(status_code=200, payload={}, _raise_on_json=True),
    )
    with pytest.raises(AmazfitAuthError):
        await login(http, _config())
