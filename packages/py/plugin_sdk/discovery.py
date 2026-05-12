"""Filesystem discovery — walk ``plugins/<kind>/<id>/plugin.yaml``.

Convention over registry: the loader does not read a central index;
it walks the on-disk layout. Adding a plugin is "drop a directory
under ``plugins/<kind>/`` with a manifest"; removing one is "delete
the directory." No ceremony, no shipping a registry update.

Discovery is intentionally read-only and idempotent — the registry
generator (:mod:`plugin_sdk.registry`) calls this module to build
``.generated/plugin-registry.json`` at build time. The runtime can
also call it directly to discover plugins on each boot, which is what
Phase 6's tests do.

The default plugin root is ``<repo>/plugins/`` resolved relative to
the repo root. Tests pass an explicit root via the ``plugins_dir``
parameter to keep the discovery deterministic.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import PluginManifestError
from .manifest import PluginManifest

_KINDS: tuple[str, ...] = ("sources", "narrators", "agents")
_KIND_TO_SINGULAR: dict[str, str] = {
    "sources": "source",
    "narrators": "narrator",
    "agents": "agent",
}


def _default_plugins_dir() -> Path:
    """Resolve the default plugin root in both repo and Docker layouts.

    In the source tree this module lives at
    ``packages/py/plugin_sdk/discovery.py`` and the plugin root is
    ``<repo>/plugins``. In the Docker image the module is copied to
    ``/app/plugin_sdk/discovery.py`` and the plugin root is ``/app/plugins``.
    ``parents[3]`` was correct only for the source tree and crashes in the
    flattened image layout, so resolve defensively.
    """
    env_path = os.getenv("HDH_PLUGINS_DIR")
    if env_path:
        return Path(env_path)

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "plugins"
        if candidate.exists():
            return candidate
    return Path("/app/plugins")


_DEFAULT_PLUGINS_DIR = _default_plugins_dir()


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    """One plugin found on disk."""

    kind: str  # singular: source | narrator | agent
    plugin_id: str
    manifest: PluginManifest
    plugin_dir: Path  # absolute path to the plugin directory


def discover(plugins_dir: Path | None = None) -> list[DiscoveredPlugin]:
    """Walk ``plugins_dir`` and return every plugin with a valid manifest.

    Plugins with malformed manifests raise :class:`PluginManifestError`
    immediately — discovery is fail-loud by design. A plugin author
    catches this in CI before shipping. The runtime caller can wrap
    in try/except if it wants tolerant discovery (the audit pattern
    flags silent skips, so the default is loud).
    """
    root = plugins_dir if plugins_dir is not None else _DEFAULT_PLUGINS_DIR
    out: list[DiscoveredPlugin] = []
    for kind_dir_name in _KINDS:
        kind_dir = root / kind_dir_name
        if not kind_dir.is_dir():
            continue
        for plugin_dir in sorted(kind_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "plugin.yaml"
            if not manifest_path.is_file():
                continue
            manifest = load_manifest(manifest_path)
            singular = _KIND_TO_SINGULAR[kind_dir_name]
            if manifest.kind != singular:
                raise PluginManifestError(
                    plugin_dir=str(plugin_dir),
                    message=(
                        f"manifest kind={manifest.kind!r} does not match "
                        f"directory kind={singular!r}"
                    ),
                )
            out.append(
                DiscoveredPlugin(
                    kind=singular,
                    plugin_id=manifest.id,
                    manifest=manifest,
                    plugin_dir=plugin_dir.resolve(),
                )
            )
    return out


def load_manifest(manifest_path: Path) -> PluginManifest:
    """Parse one plugin.yaml into a validated :class:`PluginManifest`.

    Raises :class:`PluginManifestError` on YAML parse failure or
    Pydantic validation failure. The ``__cause__`` chain carries the
    original exception so the operator can see exactly which field
    failed.
    """
    plugin_dir = str(manifest_path.parent)
    try:
        raw = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as exc:
        raise PluginManifestError(
            plugin_dir=plugin_dir,
            message=f"plugin.yaml is not valid YAML: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise PluginManifestError(
            plugin_dir=plugin_dir,
            message=f"plugin.yaml top level must be a mapping; got {type(raw).__name__}",
        )
    try:
        return PluginManifest.model_validate(raw)
    except Exception as exc:
        raise PluginManifestError(
            plugin_dir=plugin_dir,
            message=f"plugin.yaml fails PluginManifest schema: {exc}",
        ) from exc


def by_kind(plugins: Iterable[DiscoveredPlugin], *, kind: str) -> list[DiscoveredPlugin]:
    """Filter discovered plugins to one kind."""
    return [p for p in plugins if p.kind == kind]
