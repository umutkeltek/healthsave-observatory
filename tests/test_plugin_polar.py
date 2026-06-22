"""Polar AccessLink source plugin structural tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugin_sdk import PluginManifest, Source, discover, is_sdk_compatible, load_manifest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "sources" / "polar"


def test_polar_plugin_directory_exists():
    assert PLUGIN_DIR.is_dir()
    for name in ("plugin.yaml", "__init__.py", "oauth.py", "fetch.py", "normalize.py", "README.md"):
        assert (PLUGIN_DIR / name).is_file()


def test_polar_manifest_parses_and_declares_contract():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")

    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "polar-accesslink"
    assert manifest.kind == "source"
    assert manifest.entrypoint == "plugins.sources.polar:PolarSource"
    assert is_sdk_compatible(manifest)
    assert "measurement.workouts" in manifest.emits
    assert "measurement.exercise_duration_seconds" in manifest.emits


def test_polar_manifest_declares_network_and_secrets():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")

    assert manifest.permissions.network is True
    assert {
        "POLAR_CLIENT_ID",
        "POLAR_CLIENT_SECRET",
        "POLAR_REDIRECT_URI",
        "HDH_TOKEN_ENC_KEY",
    }.issubset(set(manifest.permissions.secrets))
    capability_names = {cap.name for cap in manifest.permissions.capabilities}
    assert "write:oauth_tokens" in capability_names
    assert "write:measurements" in capability_names
    assert "network:www.polaraccesslink.com" in capability_names


def test_polar_entrypoint_is_source_subclass():
    from plugins.sources.polar import PolarSource

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = PolarSource(manifest)

    assert isinstance(plugin, Source)


def test_discover_finds_polar_plugin():
    found = [p for p in discover(REPO_ROOT / "plugins") if p.plugin_id == "polar-accesslink"]

    assert len(found) == 1
    assert found[0].plugin_dir == PLUGIN_DIR.resolve()
