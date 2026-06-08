# SPDX-License-Identifier: Apache-2.0
"""Plugin manifest — the contract every plugin declares.

Loaded from ``plugins/<kind>/<id>/plugin.yaml`` (filesystem
discovery; no central registry). The fields here are also the
shape the contract test ``tests/plugin-compliance/`` enforces on
every shipped plugin.
"""

from __future__ import annotations

from typing import Literal

from ._base import V2Model


class PluginCapability(V2Model):
    """A capability a plugin declares it needs.

    Capabilities use the ``read:<scope>`` / ``write:<scope>`` form
    (e.g. ``read:hrv``, ``write:notifications``) so the policy layer
    can match on prefix.
    """

    name: str
    description: str | None = None


class PluginPermissions(V2Model):
    """Runtime permissions a plugin requests."""

    network: bool = False
    secrets: list[str] = []
    capabilities: list[PluginCapability] = []


class PluginManifest(V2Model):
    """Every plugin's plugin.yaml validates against this.

    ``sdk_version`` is the SDK version range the plugin targets
    (semver, e.g. ``">=0.1,<0.2"``). The loader rejects plugins
    whose declared range doesn't include the running core SDK.
    Adding this from day one means we can evolve the SDK contract
    without silently breaking community plugins.
    """

    id: str
    name: str
    kind: Literal["source", "narrator", "agent"]
    version: str
    sdk_version: str
    language: Literal["python", "typescript"] = "python"
    entrypoint: str
    config_schema: str | None = None
    permissions: PluginPermissions = PluginPermissions()
    emits: list[str] = []
    consumes: list[str] = []
    requires: list[str] = []
