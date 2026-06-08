# SPDX-License-Identifier: Apache-2.0
"""Plugin registry — materializes discovered plugins into a JSON index.

The registry file lives at ``plugins/.generated/plugin-registry.json``
and is the wire-stable artifact that the runtime, the dashboard, and
any out-of-process consumer can read without invoking discovery
themselves.

Phase 6 generates the registry on demand (via this module's CLI) and
in tests. Production deploys can either:

  * Generate at build time (CI hook), commit the file, and read at
    runtime — deterministic, no boot-time YAML walks. Recommended.
  * Generate at boot time inside the lifespan — simpler, no build
    coupling, but slower startup as the plugin set grows.

The registry is keyed on ``(kind, plugin_id)`` so two plugins with
the same id but different kinds (e.g. a "weather" Source and a
"weather" Narrator) coexist cleanly. Within one kind the id is unique.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .__about__ import SDK_VERSION
from .discovery import DiscoveredPlugin, discover
from .manifest import PluginManifest, is_sdk_compatible


def _portable_plugin_dir(plugin_dir: Path) -> str:
    """Return a registry path that can be committed and reused elsewhere."""
    resolved = plugin_dir.resolve()
    for parent in resolved.parents:
        if parent.name == "plugins":
            return resolved.relative_to(parent.parent).as_posix()
    return resolved.as_posix()


def _entry(p: DiscoveredPlugin) -> dict[str, Any]:
    """One entry in the registry JSON.

    Carries the manifest as-is plus the resolved plugin_dir (relative
    to repo root for portability across machines) and a derived
    ``compatible`` boolean so consumers can decide load-or-skip at a
    glance without re-running the semver matcher.
    """
    return {
        "kind": p.kind,
        "id": p.plugin_id,
        "plugin_dir": _portable_plugin_dir(p.plugin_dir),
        "compatible_with_running_sdk": is_sdk_compatible(p.manifest),
        "manifest": p.manifest.model_dump(mode="json"),
    }


def build_registry(plugins: Iterable[DiscoveredPlugin] | None = None) -> dict[str, Any]:
    """Materialize discovered plugins into the registry JSON shape.

    The returned dict is the canonical wire shape — the file written
    to disk is just ``json.dumps(registry, indent=2, sort_keys=True)``
    of this. Sort keys produce a stable diff across runs.
    """
    found = list(plugins) if plugins is not None else discover()
    found.sort(key=lambda p: (p.kind, p.plugin_id))
    return {
        "sdk_version": SDK_VERSION,
        "plugins": [_entry(p) for p in found],
    }


def write_registry(
    registry_path: Path | None = None,
    *,
    plugins: Iterable[DiscoveredPlugin] | None = None,
) -> Path:
    """Write the registry to ``plugins/.generated/plugin-registry.json``.

    Returns the absolute path written. Creates the ``.generated``
    directory if missing. Existing file is overwritten — the file is
    a build artifact, not a hand-edited config.
    """
    if registry_path is None:
        from .discovery import _DEFAULT_PLUGINS_DIR

        registry_path = _DEFAULT_PLUGINS_DIR / ".generated" / "plugin-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry = build_registry(plugins=plugins)
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    return registry_path.resolve()


def load_registry(registry_path: Path) -> dict[str, Any]:
    """Read a previously-written registry JSON. Returns the raw dict.

    Callers that want typed access can ``.model_validate(entry["manifest"])``
    each plugin into a :class:`PluginManifest`.
    """
    return json.loads(registry_path.read_text())


def materialize_manifest(entry: dict[str, Any]) -> PluginManifest:
    """Convenience: turn one registry entry's manifest dict back into
    a :class:`PluginManifest` instance.
    """
    return PluginManifest.model_validate(entry["manifest"])


if __name__ == "__main__":
    # Phase 6 CLI: regenerate the registry. Used in CI ("did anyone
    # forget to commit a plugin?") and locally after adding a plugin.
    written = write_registry()
    print(f"wrote {written}")
