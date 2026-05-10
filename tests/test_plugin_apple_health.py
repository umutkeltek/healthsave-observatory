"""Apple Health (HealthSave bridge) plugin contract tests.

Phase 6 ships this as the first first-party Source plugin. Tests
verify the manifest is well-formed, the entrypoint resolves to a
``plugin_sdk.Source`` subclass, and the discovery walk finds it in
the live ``plugins/`` directory.

The wrapper's ``ingest`` method itself is implicitly covered by
``tests/test_api_contract.py``: the route → ingest pipeline path is
the same one the plugin delegates to, so any regression there
also fails the route tests. We do NOT duplicate that integration
coverage here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_sdk import (  # noqa: E402
    PluginManifest,
    Source,
    discover,
    is_sdk_compatible,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "sources" / "apple_health_healthsave"


def test_apple_health_plugin_directory_exists():
    assert PLUGIN_DIR.is_dir(), f"Apple Health plugin directory missing: {PLUGIN_DIR}"
    assert (PLUGIN_DIR / "plugin.yaml").is_file()
    assert (PLUGIN_DIR / "__init__.py").is_file()
    assert (PLUGIN_DIR / "README.md").is_file()


def test_apple_health_manifest_parses_and_validates():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "apple-health-healthsave"
    assert manifest.kind == "source"
    assert manifest.language == "python"
    # SDK target accepts the running SDK.
    assert is_sdk_compatible(manifest)


def test_apple_health_manifest_emits_every_route_supported_metric():
    """If iOS POSTs a metric, the plugin manifest should declare it.

    The route's per-metric dispatch (storage.timescale.measurements._ingest_metric)
    handles a fixed set of dedicated tables + a quantity_samples
    catch-all. The manifest enumerates the headline metrics; the
    catch-all is named explicitly so operators know what's covered.
    """
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    declared = set(manifest.emits)
    must_include = {
        "measurement.heart_rate",
        "measurement.hrv",
        "measurement.sleep_analysis",
        "measurement.workouts",
        "measurement.activity_summaries",
        "measurement.quantity_samples",
    }
    missing = must_include - declared
    assert not missing, f"plugin manifest is missing declared emits: {missing}"


def test_apple_health_entrypoint_resolves_to_source_subclass():
    """``entrypoint: module:Class`` must resolve to a Source subclass."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert issubclass(cls, Source), f"{cls!r} is not a Source subclass"


def test_apple_health_class_instantiates_with_manifest():
    """Loader will call ``cls(manifest)``; that must succeed."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls(manifest)
    assert isinstance(instance, Source)
    assert instance.manifest is manifest


def test_apple_health_plugin_discovered_under_real_plugins_dir():
    """``discover()`` walks the actual ``plugins/`` and finds it."""
    found = discover()
    matches = [p for p in found if p.plugin_id == "apple-health-healthsave"]
    assert len(matches) == 1, (
        f"expected exactly one apple-health-healthsave plugin; found {len(matches)}"
    )
    only = matches[0]
    assert only.kind == "source"
    assert only.plugin_dir == PLUGIN_DIR.resolve()


def test_apple_health_plugin_permissions_are_minimal():
    """No network, no secrets — the plugin operates entirely inside the API process."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert manifest.permissions.network is False
    assert manifest.permissions.secrets == []
    # The two declared capabilities are storage writes, not arbitrary side effects.
    capability_names = {c.name for c in manifest.permissions.capabilities}
    assert capability_names == {"write:raw_ingestion_log", "write:measurements"}


@pytest.mark.asyncio
async def test_apple_health_ingest_is_a_thin_wrapper_returns_zero_on_empty_payload():
    """Empty payload → no rows committed, no rejected."""
    from plugins.sources.apple_health_healthsave import AppleHealthSource

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    result = await plugin.ingest(
        {
            "session": object(),  # not invoked when samples is empty
            "device_id": 1,
            "metric": "heart_rate",
            "samples": [],
        }
    )
    assert result == {"accepted": 0, "rejected": 0}
