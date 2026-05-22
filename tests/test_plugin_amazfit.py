"""Amazfit plugin scaffold + token-import helper tests.

Mirrors ``test_plugin_whoop.py``: pin manifest validity, entrypoint
resolution, scaffold contract, and the token-import surface.

The H-revise scaffold replaces P6-a's password-login flow with
operator-provided token import. Tests below exercise the new helpers
(``token_from_app_token_string``, ``token_from_huami_token_output``,
``token_from_env``) and the slimmed ``AmazfitClientConfig``. The
``AmazfitSource.ingest`` ``NotImplementedError`` pin stays — it goes
away in the H-ingest commit.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

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

from plugins.sources.amazfit import (  # noqa: E402
    DATA_API_HEADERS_BASE,
    PROVIDER,
    REGION_BASE_URLS,
    AmazfitSource,
)

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
        "AMAZFIT_APP_TOKEN",
        "AMAZFIT_USER_ID",
        "AMAZFIT_REGION",
        "HDH_TOKEN_ENC_KEY",
    }
    missing = must_include - declared
    assert not missing, f"manifest missing secrets: {missing}"
    # H-revise: password-based secrets are gone from the public surface.
    assert "AMAZFIT_EMAIL" not in declared
    assert "AMAZFIT_PASSWORD" not in declared


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
async def test_amazfit_ingest_no_op_when_token_store_returns_none():
    """H-ingest: no stored token = silent no-op (operator hasn't run
    the authorize CLI yet). Drives the scaffold test that previously
    pinned NotImplementedError until H-ingest landed.
    """

    class _NoopTokenStore:
        async def get_token(self, *args, **kwargs):
            return None

    class _NoopStorage:
        async def get_or_create_device(self, *a, **k):
            return 1

        async def ingest_metric(self, *a, **k):
            return 0

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AmazfitSource(manifest)
    result = await plugin.ingest(
        {
            "storage": _NoopStorage(),
            "session": object(),
            "http_client": object(),
            "token_store": _NoopTokenStore(),
        }
    )
    assert result == {"accepted": 0, "rejected": 0}


def test_region_base_urls_target_current_zepp_host():
    """H-revise: probe verified api-mifit-us3.zepp.com is the live US host.
    This test catches accidental reversion to api-mifit-us2.huami.com.
    """
    assert REGION_BASE_URLS["us"] == "https://api-mifit-us3.zepp.com"
    for v in REGION_BASE_URLS.values():
        assert "huami.com" not in v, "huami.com hosts are deprecated"
        assert v.startswith("https://")


def test_data_api_headers_base_carries_required_keys():
    # apptoken + x-request-id + r are added per-call; appname + appplatform are static.
    assert DATA_API_HEADERS_BASE["appname"] == "com.huami.midong"
    assert DATA_API_HEADERS_BASE["appplatform"] == "ios_phone"


# ─── AmazfitClientConfig ────────────────────────────────────────────────


def test_amazfit_config_from_env_reads_region(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    monkeypatch.setenv("AMAZFIT_REGION", "eu")
    config = AmazfitClientConfig.from_env()
    assert config.region == "eu"
    assert config.base_url == "https://api-mifit-de.zepp.com"


def test_amazfit_config_defaults_region_to_us(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    monkeypatch.delenv("AMAZFIT_REGION", raising=False)
    config = AmazfitClientConfig.from_env()
    assert config.region == "us"
    assert config.base_url == "https://api-mifit-us3.zepp.com"


def test_amazfit_config_unknown_region_falls_back_to_us():
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    config = AmazfitClientConfig(region="atlantis")
    assert config.base_url == "https://api-mifit-us3.zepp.com"


def test_amazfit_config_no_longer_accepts_email_or_password():
    """H-revise removed email + password from the public config dataclass.
    Catching their re-introduction would re-expose the deprecated flow.
    """
    from plugins.sources.amazfit.auth import AmazfitClientConfig

    with pytest.raises(TypeError):
        AmazfitClientConfig(email="u@e", password="pw")  # type: ignore[call-arg]


# ─── token_from_app_token_string ────────────────────────────────────────


def test_token_from_app_token_string_happy_path():
    from plugins.sources.amazfit.auth import token_from_app_token_string

    token = token_from_app_token_string(
        access_token="EXAMPLE_BLOB_xxxx",
        user_id="3311629755",
        region="us",
    )
    assert token.provider == PROVIDER
    assert token.access_token == "EXAMPLE_BLOB_xxxx"
    assert token.refresh_token is None
    assert token.metadata["region"] == "us"
    assert token.metadata["user_id"] == "3311629755"
    assert token.metadata["base_url"] == "https://api-mifit-us3.zepp.com"
    assert token.expires_at is not None


def test_token_from_app_token_string_trims_whitespace():
    from plugins.sources.amazfit.auth import token_from_app_token_string

    token = token_from_app_token_string(
        access_token="  EXAMPLE_BLOB  ",
        user_id="  3311629755  ",
        region="  EU ",
    )
    assert token.access_token == "EXAMPLE_BLOB"
    assert token.metadata["user_id"] == "3311629755"
    assert token.metadata["region"] == "eu"


def test_token_from_app_token_string_rejects_empty_access_token():
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_app_token_string

    with pytest.raises(AmazfitAuthError):
        token_from_app_token_string(access_token="", user_id="42", region="us")


def test_token_from_app_token_string_rejects_non_numeric_user_id():
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_app_token_string

    with pytest.raises(AmazfitAuthError):
        token_from_app_token_string(access_token="X", user_id="not-numeric", region="us")


def test_token_from_app_token_string_unknown_region_falls_back_to_us():
    from plugins.sources.amazfit.auth import token_from_app_token_string

    token = token_from_app_token_string(access_token="X", user_id="42", region="atlantis")
    assert token.metadata["base_url"] == "https://api-mifit-us3.zepp.com"


# ─── token_from_huami_token_output ──────────────────────────────────────


# Captured from a real huami-token --no_logout run (2026-05-22). The
# blobs below are deliberately shortened/redacted for the fixture.
_FIXTURE_HUAMI_TOKEN_OUTPUT = """\
2026-05-22 23:10:08.408 | INFO | huami_token.zepp:login:68 - Logging in...
2026-05-22 23:10:08.408 | DEBUG | huami_token.zepp:tokens:83 - encoded_payload=REDACTED
2026-05-22 23:10:11.395 | INFO | huami_token.zepp:login:71 - Logged in! User id: 3311629755

No logout!
app_token=FAKE_APP_TOKEN_FOR_FIXTURE_ONLY
login_token=FAKE_LOGIN_TOKEN_INTERMEDIATE
"""


def test_token_from_huami_token_output_happy_path():
    from plugins.sources.amazfit.auth import token_from_huami_token_output

    token = token_from_huami_token_output(_FIXTURE_HUAMI_TOKEN_OUTPUT, region="us")
    assert token.access_token == "FAKE_APP_TOKEN_FOR_FIXTURE_ONLY"
    assert token.metadata["user_id"] == "3311629755"
    assert token.metadata["region"] == "us"
    assert token.metadata["base_url"] == "https://api-mifit-us3.zepp.com"


def test_token_from_huami_token_output_region_default_is_us():
    from plugins.sources.amazfit.auth import token_from_huami_token_output

    token = token_from_huami_token_output(_FIXTURE_HUAMI_TOKEN_OUTPUT)
    assert token.metadata["region"] == "us"


def test_token_from_huami_token_output_rejects_empty():
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_huami_token_output

    with pytest.raises(AmazfitAuthError):
        token_from_huami_token_output("")


def test_token_from_huami_token_output_rejects_missing_app_token():
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_huami_token_output

    text = "No logout!\nlogin_token=FAKE\n... User id: 42\n"
    with pytest.raises(AmazfitAuthError) as exc:
        token_from_huami_token_output(text)
    assert "app_token" in str(exc.value)


def test_token_from_huami_token_output_rejects_missing_user_id():
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_huami_token_output

    text = "app_token=FAKE\n"
    with pytest.raises(AmazfitAuthError) as exc:
        token_from_huami_token_output(text)
    assert "User id" in str(exc.value)


def test_token_from_huami_token_output_anchors_on_literal_field_names_not_logging_format():
    """The parser uses literal ``app_token=`` and ``User id: <digits>`` anchors.
    A cosmetic upstream change to the logger prefix should not break us.
    """
    from plugins.sources.amazfit.auth import token_from_huami_token_output

    weirdly_formatted = """\
[12:34:56] [INFO] zepp - logging in
[12:34:57] [INFO] zepp - Logged in! User id: 99887766
SOMETHING WEIRD
app_token=TOKEN_WITH_FUNKY_BANNER
login_token=intermediate
"""
    token = token_from_huami_token_output(weirdly_formatted)
    assert token.access_token == "TOKEN_WITH_FUNKY_BANNER"
    assert token.metadata["user_id"] == "99887766"


# ─── token_from_env ─────────────────────────────────────────────────────


def test_token_from_env_happy_path(monkeypatch):
    from plugins.sources.amazfit.auth import token_from_env

    monkeypatch.setenv("AMAZFIT_APP_TOKEN", "ENV_TOKEN")
    monkeypatch.setenv("AMAZFIT_USER_ID", "42")
    monkeypatch.setenv("AMAZFIT_REGION", "eu")

    token = token_from_env()
    assert token.access_token == "ENV_TOKEN"
    assert token.metadata["user_id"] == "42"
    assert token.metadata["region"] == "eu"
    assert token.metadata["base_url"] == "https://api-mifit-de.zepp.com"


def test_token_from_env_missing_app_token_raises(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_env

    monkeypatch.delenv("AMAZFIT_APP_TOKEN", raising=False)
    monkeypatch.setenv("AMAZFIT_USER_ID", "42")
    with pytest.raises(AmazfitAuthError):
        token_from_env()


def test_token_from_env_missing_user_id_raises(monkeypatch):
    from plugins.sources.amazfit.auth import AmazfitAuthError, token_from_env

    monkeypatch.setenv("AMAZFIT_APP_TOKEN", "X")
    monkeypatch.delenv("AMAZFIT_USER_ID", raising=False)
    with pytest.raises(AmazfitAuthError):
        token_from_env()


# ─── deprecated surfaces stay deprecated ───────────────────────────────


def test_login_symbol_removed_from_auth_module():
    """H-revise: the password-flow ``login`` function was removed.
    Catching a re-introduction prevents accidental revival of the
    deprecated v2/client/login flow.
    """
    from plugins.sources.amazfit import auth

    assert not hasattr(auth, "login"), "login() was removed in H-revise"
    assert not hasattr(auth, "md5_password"), "md5_password() was removed in H-revise"
    assert not hasattr(auth, "AUTH_LOGIN_URL")
