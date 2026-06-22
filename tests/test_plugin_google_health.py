"""Google Health API source plugin structural tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugin_sdk import PluginManifest, Source, discover, is_sdk_compatible, load_manifest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "sources" / "google_health"


def test_google_health_plugin_directory_exists() -> None:
    assert PLUGIN_DIR.is_dir()
    for name in ("plugin.yaml", "__init__.py", "oauth.py", "fetch.py", "normalize.py", "README.md"):
        assert (PLUGIN_DIR / name).is_file()


def test_google_health_manifest_parses_and_declares_contract() -> None:
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")

    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "google-health-api"
    assert manifest.kind == "source"
    assert manifest.entrypoint == "plugins.sources.google_health:GoogleHealthSource"
    assert is_sdk_compatible(manifest)
    assert "measurement.step_count" in manifest.emits


def test_google_health_manifest_declares_network_and_secrets() -> None:
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")

    assert manifest.permissions.network is True
    assert {
        "GOOGLE_HEALTH_CLIENT_ID",
        "GOOGLE_HEALTH_CLIENT_SECRET",
        "GOOGLE_HEALTH_REDIRECT_URI",
        "HDH_TOKEN_ENC_KEY",
    }.issubset(set(manifest.permissions.secrets))

    capability_names = {cap.name for cap in manifest.permissions.capabilities}
    assert "write:oauth_tokens" in capability_names
    assert "write:measurements" in capability_names
    assert "network:health.googleapis.com" in capability_names
    assert "network:oauth2.googleapis.com" in capability_names


def test_google_health_source_entrypoint_is_loadable() -> None:
    from plugins.sources.google_health import GoogleHealthSource

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = GoogleHealthSource(manifest)

    assert isinstance(plugin, Source)
    assert plugin.manifest.id == "google-health-api"


def test_google_health_plugin_discovered_from_real_plugins_tree() -> None:
    found = [p for p in discover(REPO_ROOT / "plugins") if p.plugin_id == "google-health-api"]

    assert len(found) == 1
    assert found[0].manifest.entrypoint == "plugins.sources.google_health:GoogleHealthSource"
