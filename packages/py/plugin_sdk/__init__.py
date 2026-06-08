# SPDX-License-Identifier: Apache-2.0
"""Plugin SDK — the contract every datahub plugin builds against.

Phase 6 ships v0.1.0 with three plugin kinds (Source, Narrator,
Agent), filesystem discovery (``plugins/<kind>/<id>/plugin.yaml``),
and a generated registry (``plugins/.generated/plugin-registry.json``).
The Apple Health source under ``plugins/sources/apple-health-healthsave/``
is the first first-party plugin and the worked example for plugin
authors.

Public surface (the imports plugin authors actually use):

  * :class:`Source`, :class:`Narrator`, :class:`Agent` — abstract
    base classes for the three kinds.
  * :class:`PluginManifest`, :class:`PluginCapability`,
    :class:`PluginPermissions` — the manifest schema (re-exported
    from ``contracts.plugins``).
  * :func:`assert_sdk_compatible`, :func:`is_sdk_compatible` — semver
    compatibility checks.
  * :data:`SDK_VERSION` — the running contract version.

Loader / registry surface (for the runtime, not plugin authors):

  * :func:`discover` — walk ``plugins/`` and return found plugins.
  * :func:`build_registry`, :func:`write_registry`, :func:`load_registry`
    — generate / consume the JSON registry artifact.

Errors all subclass :class:`PluginError`; specific subclasses for
manifest, version, entrypoint, and not-found cases live in
:mod:`plugin_sdk.errors`.
"""

from __future__ import annotations

from .__about__ import SDK_VERSION, SDK_VERSION_TUPLE
from .base import Agent, Narrator, Plugin, Source
from .discovery import DiscoveredPlugin, discover, load_manifest
from .errors import (
    PluginEntrypointError,
    PluginError,
    PluginManifestError,
    PluginNotFoundError,
    PluginSdkVersionMismatch,
)
from .loader import load_plugin
from .manifest import (
    PluginCapability,
    PluginManifest,
    PluginPermissions,
    assert_sdk_compatible,
    is_sdk_compatible,
)
from .registry import (
    build_registry,
    load_registry,
    materialize_manifest,
    write_registry,
)
from .runtime import (
    AgentHealthError,
    AgentLifecycleError,
    AgentObserveError,
    AgentProposeError,
    AgentRuntimeError,
    AgentTimeoutError,
    error_boundary,
    with_deadline,
)

__all__ = [
    # versioning
    "SDK_VERSION",
    "SDK_VERSION_TUPLE",
    # base classes
    "Plugin",
    "Source",
    "Narrator",
    "Agent",
    # manifest
    "PluginManifest",
    "PluginCapability",
    "PluginPermissions",
    "assert_sdk_compatible",
    "is_sdk_compatible",
    # discovery + registry
    "DiscoveredPlugin",
    "discover",
    "load_manifest",
    "build_registry",
    "write_registry",
    "load_registry",
    "materialize_manifest",
    # loader (Phase 7-pre)
    "load_plugin",
    # runtime contracts (Phase 7-pre)
    "AgentRuntimeError",
    "AgentLifecycleError",
    "AgentHealthError",
    "AgentObserveError",
    "AgentProposeError",
    "AgentTimeoutError",
    "error_boundary",
    "with_deadline",
    # errors
    "PluginError",
    "PluginManifestError",
    "PluginSdkVersionMismatch",
    "PluginNotFoundError",
    "PluginEntrypointError",
]
