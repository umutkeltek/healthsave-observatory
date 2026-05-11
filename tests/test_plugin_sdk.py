"""Plugin SDK contract tests (Phase 6).

Covers:

* The public surface from ``plugin_sdk`` is importable and exposes
  the documented names.
* ``PluginManifest`` validates good manifests and rejects malformed
  ones (extra='forbid' from the V2Model base catches drift).
* ``is_sdk_compatible`` / ``assert_sdk_compatible`` honor every
  range form Phase 6 ships (``"*"``, exact, ``">=X,<Y"``,
  ``">=X"``).
* ``discover`` walks the on-disk layout and rejects manifests whose
  declared ``kind`` disagrees with their parent directory.
* ``build_registry`` / ``write_registry`` / ``load_registry``
  round-trip cleanly and the JSON is sort-stable across runs.
* The base classes (``Source``, ``Narrator``, ``Agent``) refuse to
  be instantiated when their abstract methods are not overridden.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_sdk import (  # noqa: E402
    SDK_VERSION,
    Agent,
    DiscoveredPlugin,
    Narrator,
    Plugin,
    PluginCapability,
    PluginManifest,
    PluginManifestError,
    PluginPermissions,
    PluginSdkVersionMismatch,
    Source,
    assert_sdk_compatible,
    build_registry,
    discover,
    is_sdk_compatible,
    load_manifest,
    load_registry,
    materialize_manifest,
    write_registry,
)

# ──────────────────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────────────────


def test_sdk_version_is_semver():
    """v0.1.0 ships Phase 6. Bump on every breaking change."""
    parts = SDK_VERSION.split(".")
    assert len(parts) == 3
    for p in parts:
        assert p.isdigit()


def test_public_surface_exposes_documented_names():
    """The names listed in the package docstring must be importable."""
    names = [
        "SDK_VERSION",
        "Plugin",
        "Source",
        "Narrator",
        "Agent",
        "PluginManifest",
        "PluginCapability",
        "PluginPermissions",
        "assert_sdk_compatible",
        "is_sdk_compatible",
        "DiscoveredPlugin",
        "discover",
        "load_manifest",
        "build_registry",
        "write_registry",
        "load_registry",
        "materialize_manifest",
    ]
    import plugin_sdk

    for name in names:
        assert hasattr(plugin_sdk, name), f"plugin_sdk missing {name}"


# ──────────────────────────────────────────────────────────────────────
# Manifest schema
# ──────────────────────────────────────────────────────────────────────


def _good_manifest_dict(**overrides):
    base = {
        "id": "apple-health-healthsave",
        "name": "Apple Health (HealthSave bridge)",
        "kind": "source",
        "version": "1.0.0",
        "sdk_version": ">=0.1,<0.2",
        "language": "python",
        "entrypoint": "plugins.sources.apple_health_healthsave:AppleHealthSource",
        "emits": ["measurement.heart_rate", "measurement.hrv"],
    }
    base.update(overrides)
    return base


def test_plugin_manifest_validates_a_good_manifest():
    m = PluginManifest.model_validate(_good_manifest_dict())
    assert m.id == "apple-health-healthsave"
    assert m.kind == "source"
    assert m.sdk_version == ">=0.1,<0.2"
    assert "measurement.heart_rate" in m.emits


def test_plugin_manifest_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_good_manifest_dict(kind="transform"))


def test_plugin_manifest_rejects_extra_field():
    """V2Model has extra='forbid' — silent drift is the smell."""
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_good_manifest_dict(undeclared_field="oops"))


def test_plugin_capability_is_a_simple_pair():
    cap = PluginCapability.model_validate({"name": "read:hrv", "description": "read HRV"})
    assert cap.name == "read:hrv"
    assert cap.description == "read HRV"


def test_plugin_permissions_defaults_are_safe():
    """Default permissions: no network, no secrets, no capabilities."""
    p = PluginPermissions()
    assert p.network is False
    assert p.secrets == []
    assert p.capabilities == []


# ──────────────────────────────────────────────────────────────────────
# SDK-version range matcher
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "declared,running,expected",
    [
        ("*", "0.1.0", True),
        ("*", "9.9.9", True),
        ("0.1.0", "0.1.0", True),
        ("0.1.0", "0.1.1", False),
        (">=0.1", "0.1.0", True),
        (">=0.1", "0.5.0", True),
        (">=0.1,<0.2", "0.1.5", True),
        (">=0.1,<0.2", "0.2.0", False),
        (">=0.1,<0.2", "0.0.9", False),
        (">0.1,<=0.2", "0.2.0", True),
        (">0.1,<=0.2", "0.1.0", False),
    ],
)
def test_sdk_version_matcher_table(declared, running, expected):
    m = PluginManifest.model_validate(_good_manifest_dict(sdk_version=declared))
    assert is_sdk_compatible(m, running=running) is expected


def test_assert_sdk_compatible_raises_on_mismatch():
    m = PluginManifest.model_validate(_good_manifest_dict(sdk_version="<0.1"))
    with pytest.raises(PluginSdkVersionMismatch) as exc:
        assert_sdk_compatible(m, running="0.1.0")
    assert exc.value.plugin_id == m.id
    assert exc.value.declared == "<0.1"
    assert exc.value.running == "0.1.0"


# ──────────────────────────────────────────────────────────────────────
# Discovery
# ──────────────────────────────────────────────────────────────────────


def _write_plugin(plugin_dir: Path, manifest_dict: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml

    (plugin_dir / "plugin.yaml").write_text(_yaml.safe_dump(manifest_dict))


def test_discover_walks_kind_directories(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))
    _write_plugin(
        plugins / "narrators" / "beta",
        _good_manifest_dict(id="beta", kind="narrator", entrypoint="x:Y"),
    )

    found = discover(plugins)
    assert {p.plugin_id for p in found} == {"alpha", "beta"}
    assert {p.kind for p in found} == {"source", "narrator"}


def test_discover_skips_directories_without_a_manifest(tmp_path: Path):
    plugins = tmp_path / "plugins"
    (plugins / "sources" / "no_manifest").mkdir(parents=True)
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))

    found = discover(plugins)
    assert [p.plugin_id for p in found] == ["alpha"]


def test_discover_rejects_kind_directory_mismatch(tmp_path: Path):
    """Manifest kind must agree with the parent directory name."""
    plugins = tmp_path / "plugins"
    # Put a 'source' kind under sources/ — wrong, fail loud.
    _write_plugin(
        plugins / "sources" / "bad",
        _good_manifest_dict(id="bad", kind="narrator", entrypoint="x:Y"),
    )

    with pytest.raises(PluginManifestError):
        discover(plugins)


def test_load_manifest_raises_on_malformed_yaml(tmp_path: Path):
    bad = tmp_path / "plugin.yaml"
    bad.write_text("[: not valid YAML")
    with pytest.raises(PluginManifestError):
        load_manifest(bad)


def test_load_manifest_raises_on_non_mapping_top_level(tmp_path: Path):
    bad = tmp_path / "plugin.yaml"
    bad.write_text("- a list, not a mapping\n")
    with pytest.raises(PluginManifestError):
        load_manifest(bad)


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────


def test_build_registry_is_sorted_and_carries_sdk_version(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "sources" / "zebra", _good_manifest_dict(id="zebra", kind="source"))
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))

    found = discover(plugins)
    registry = build_registry(found)
    assert registry["sdk_version"] == SDK_VERSION
    # Sorted by (kind, id) — alpha before zebra.
    ids = [p["id"] for p in registry["plugins"]]
    assert ids == ["alpha", "zebra"]
    # Compatibility flag derived for each.
    assert all("compatible_with_running_sdk" in p for p in registry["plugins"])


def test_write_and_load_registry_roundtrip(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))
    found = discover(plugins)

    out_path = tmp_path / "registry.json"
    written = write_registry(out_path, plugins=found)
    assert written == out_path.resolve()

    loaded = load_registry(out_path)
    assert loaded["sdk_version"] == SDK_VERSION
    assert len(loaded["plugins"]) == 1
    assert loaded["plugins"][0]["id"] == "alpha"

    # Round-trip into a typed manifest.
    materialized = materialize_manifest(loaded["plugins"][0])
    assert isinstance(materialized, PluginManifest)
    assert materialized.id == "alpha"


def test_registry_json_is_byte_stable_across_runs(tmp_path: Path):
    """Same input → same bytes. CI can diff this."""
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))
    found = discover(plugins)
    a = json.dumps(build_registry(found), indent=2, sort_keys=True)
    b = json.dumps(build_registry(found), indent=2, sort_keys=True)
    assert a == b


# ──────────────────────────────────────────────────────────────────────
# Base classes
# ──────────────────────────────────────────────────────────────────────


def test_source_cannot_be_instantiated_without_ingest():
    """ABC + @abstractmethod refuse instantiation when ingest is missing."""

    class IncompleteSource(Source):
        pass  # no ingest()

    m = PluginManifest.model_validate(_good_manifest_dict())
    with pytest.raises(TypeError):
        IncompleteSource(m)


def test_narrator_cannot_be_instantiated_without_render():
    class IncompleteNarrator(Narrator):
        pass

    m = PluginManifest.model_validate(_good_manifest_dict(kind="narrator", entrypoint="x:Y"))
    with pytest.raises(TypeError):
        IncompleteNarrator(m)


def test_agent_cannot_be_instantiated_without_observe_and_propose():
    class IncompleteAgent(Agent):
        async def observe(self, event):
            return None

        # propose missing

    m = PluginManifest.model_validate(_good_manifest_dict(kind="agent", entrypoint="x:Y"))
    with pytest.raises(TypeError):
        IncompleteAgent(m)


def test_plugin_base_carries_manifest():
    """Common base injects the manifest so subclasses don't thread it."""

    class _S(Source):
        async def ingest(self, payload):
            return {"accepted": 1, "rejected": 0}

    m = PluginManifest.model_validate(_good_manifest_dict())
    s = _S(m)
    assert isinstance(s, Plugin)
    assert s.manifest is m


@pytest.mark.asyncio
async def test_source_default_setup_and_shutdown_are_no_ops():
    """Sources can opt out of setup/shutdown by inheriting the defaults."""

    class _S(Source):
        async def ingest(self, payload):
            return {"accepted": 0, "rejected": 0}

    m = PluginManifest.model_validate(_good_manifest_dict())
    s = _S(m)
    # Must not raise.
    await s.setup({})
    await s.shutdown()


# ──────────────────────────────────────────────────────────────────────
# Phase 7-pre-min: Agent lifecycle (start / stop / health)
# ──────────────────────────────────────────────────────────────────────


def _agent_manifest():
    return PluginManifest.model_validate(_good_manifest_dict(kind="agent", entrypoint="x:Y"))


class _MinimalAgent(Agent):
    """The minimum an Agent must implement: observe + propose. Lifecycle
    methods inherit defaults — the Phase 7-pre contract under test.
    """

    async def observe(self, event):
        return None

    async def propose(self):
        return []


@pytest.mark.asyncio
async def test_agent_default_start_is_async_noop():
    agent = _MinimalAgent(_agent_manifest())
    result = await agent.start()
    assert result is None


@pytest.mark.asyncio
async def test_agent_default_stop_is_async_noop():
    agent = _MinimalAgent(_agent_manifest())
    result = await agent.stop()
    assert result is None


@pytest.mark.asyncio
async def test_agent_default_health_returns_ok_status():
    agent = _MinimalAgent(_agent_manifest())
    result = await agent.health()
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_agent_subclass_can_override_health_without_touching_lifecycle():
    """A subclass overrides health() to surface degraded state without
    having to implement start/stop — this is the load-bearing
    ergonomics claim of the default lifecycle.
    """

    class _DegradedAgent(_MinimalAgent):
        async def health(self):
            return {"status": "degraded", "reason": "queue full", "queue_depth": 42}

    agent = _DegradedAgent(_agent_manifest())
    assert await agent.health() == {
        "status": "degraded",
        "reason": "queue full",
        "queue_depth": 42,
    }
    # Defaults still work for start/stop.
    assert await agent.start() is None
    assert await agent.stop() is None


@pytest.mark.asyncio
async def test_agent_lifecycle_methods_are_coroutine_functions():
    """The supervisor will `await agent.start()` etc. — pin the type
    so a sync override would fail this contract before failing the
    supervisor.
    """
    import inspect

    assert inspect.iscoroutinefunction(Agent.start)
    assert inspect.iscoroutinefunction(Agent.stop)
    assert inspect.iscoroutinefunction(Agent.health)


# ──────────────────────────────────────────────────────────────────────
# Sanity: DiscoveredPlugin shape
# ──────────────────────────────────────────────────────────────────────


def test_discovered_plugin_is_a_frozen_dataclass(tmp_path: Path):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins / "sources" / "alpha", _good_manifest_dict(id="alpha", kind="source"))
    from dataclasses import FrozenInstanceError

    found = discover(plugins)
    assert len(found) == 1
    p = found[0]
    assert isinstance(p, DiscoveredPlugin)
    # frozen=True dataclass raises FrozenInstanceError on assignment.
    with pytest.raises(FrozenInstanceError):
        p.kind = "narrator"
