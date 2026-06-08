# SPDX-License-Identifier: Apache-2.0
"""Plugin loader — discover + version-check + import + instantiate.

Phase 7-pre-min establishes a single canonical entry point for loading
a plugin instance by ``(plugin_id, kind)``. Bypassing :func:`load_plugin`
into raw :func:`discovery.discover` + manual ``importlib.import_module``
skips the loader-time ``sdk_version`` enforcement and is therefore the
Schrödinger-SDK risk the Phase 6 audit flagged: a plugin that targets
an incompatible SDK could be instantiated and crash inside the runtime
instead of failing at load time.

Use :func:`load_plugin` whenever you need a concrete plugin instance.
Use :func:`discovery.discover` only when you need to list / enumerate
plugins without instantiating them (the registry generator does this).
"""

from __future__ import annotations

import importlib
from pathlib import Path

from .base import Agent, Narrator, Plugin, Source
from .discovery import DiscoveredPlugin, discover
from .errors import PluginEntrypointError, PluginNotFoundError
from .manifest import assert_sdk_compatible

_KIND_TO_BASE: dict[str, type[Plugin]] = {
    "source": Source,
    "narrator": Narrator,
    "agent": Agent,
}


def load_plugin(
    plugin_id: str,
    *,
    kind: str,
    plugins_dir: Path | None = None,
) -> Plugin:
    """Discover, version-check, import, and instantiate a plugin.

    Single canonical entry point for going from ``(plugin_id, kind)`` to
    a live :class:`Plugin` instance. Raises a typed error at the FIRST
    failure on the chain — fail-loud is the right default.

    :raises PluginNotFoundError: no plugin with the given id and kind
        exists under ``plugins_dir`` (or the default plugins directory).
    :raises PluginSdkVersionMismatch: the plugin is well-formed but its
        ``sdk_version`` range excludes the running SDK. Raised BEFORE
        the entrypoint module is imported, so a load attempt cannot
        run plugin-side import side effects against an incompatible
        SDK.
    :raises PluginEntrypointError: the manifest's ``entrypoint`` could
        not be resolved — import error, missing attribute, or the
        attribute is not a subclass of the expected base class for the
        manifest's ``kind`` (e.g., a manifest declares ``kind: agent``
        but the entrypoint resolves to a class that doesn't subclass
        :class:`Agent`).
    """
    found = discover(plugins_dir)
    match: DiscoveredPlugin | None = next(
        (p for p in found if p.plugin_id == plugin_id and p.kind == kind),
        None,
    )
    if match is None:
        raise PluginNotFoundError(kind=kind, plugin_id=plugin_id)

    # SDK-version enforcement BEFORE any plugin-side import side effects.
    # The plugin module is imported via importlib.import_module below; if
    # it pulls in incompatible APIs or trips on a missing symbol, an
    # operator must see PluginSdkVersionMismatch first — not the
    # ImportError that incompatibility manifested as.
    assert_sdk_compatible(match.manifest)

    entrypoint = match.manifest.entrypoint
    module_path, _, class_name = entrypoint.partition(":")
    if not module_path or not class_name:
        raise PluginEntrypointError(
            plugin_id=plugin_id,
            entrypoint=entrypoint,
            message="entrypoint must be 'module.path:ClassName'",
        )

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise PluginEntrypointError(
            plugin_id=plugin_id,
            entrypoint=entrypoint,
            message=f"import failed: {exc}",
        ) from exc

    cls = getattr(module, class_name, None)
    if cls is None:
        raise PluginEntrypointError(
            plugin_id=plugin_id,
            entrypoint=entrypoint,
            message=f"module {module_path!r} has no attribute {class_name!r}",
        )

    expected_base = _KIND_TO_BASE.get(kind)
    if expected_base is None:
        raise PluginEntrypointError(
            plugin_id=plugin_id,
            entrypoint=entrypoint,
            message=f"unknown kind {kind!r}",
        )
    if not (isinstance(cls, type) and issubclass(cls, expected_base)):
        raise PluginEntrypointError(
            plugin_id=plugin_id,
            entrypoint=entrypoint,
            message=(
                f"{cls!r} is not a subclass of {expected_base.__name__} (manifest kind={kind!r})"
            ),
        )

    return cls(match.manifest)
