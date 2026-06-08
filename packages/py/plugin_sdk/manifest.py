# SPDX-License-Identifier: Apache-2.0
"""Plugin manifest schema + semver compatibility helpers.

The :class:`~contracts.plugins.PluginManifest` Pydantic model already
exists in ``packages/py/contracts/plugins.py`` (Phase 3). The SDK
re-exports it so plugin authors have one canonical import path
(``from plugin_sdk.manifest import PluginManifest``) without paying
attention to the contracts/ vs sdk/ boundary.

In addition to the re-export, this module owns the runtime semver
check that bridges a plugin's declared ``sdk_version`` range against
the live :data:`plugin_sdk.__about__.SDK_VERSION`.

The semver matcher implements a deliberately small subset of PEP 440 /
node-style ranges:

  * exact:        ``"0.1.0"``  matches only 0.1.0
  * caret-style:  ``">=0.1,<0.2"`` matches anything in [0.1.0, 0.2.0)
  * minimum:      ``">=0.1"`` matches 0.1.x, 0.2.x, ...
  * any:          ``"*"`` matches everything (use sparingly)

This is enough to ship Phase 6 without pulling in ``packaging`` or
``semver`` as a new dependency. If we outgrow this — multi-clause
ranges, pre-release qualifiers, build metadata — swap in
``packaging.specifiers.SpecifierSet`` and delete ``_in_range``.
"""

from __future__ import annotations

import re

from contracts.plugins import (
    PluginCapability,
    PluginManifest,
    PluginPermissions,
)

from .__about__ import SDK_VERSION
from .errors import PluginSdkVersionMismatch

__all__ = [
    "PluginCapability",
    "PluginManifest",
    "PluginPermissions",
    "assert_sdk_compatible",
    "is_sdk_compatible",
]


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_RANGE_CLAUSE_RE = re.compile(r"^(>=|<=|<|>|==)?\s*(\d+(?:\.\d+){0,2})$")


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse ``"0.1.0"`` / ``"0.1"`` into a 3-tuple of ints. Missing
    components default to 0 — the range form ``">=0.1"`` means
    ``">=0.1.0"`` and ``<0.2`` means ``<0.2.0``.
    """
    m = _VERSION_RE.match(v.strip())
    if m is None:
        raise ValueError(f"not a parseable semver: {v!r}")
    major, minor, patch = m.group(1), m.group(2), m.group(3) or "0"
    return int(major), int(minor), int(patch)


def _in_range(declared: str, version: str) -> bool:
    """Return True when ``version`` satisfies the ``declared`` range.

    ``declared`` is the plugin's stated sdk_version. ``version`` is the
    running :data:`SDK_VERSION`. Comma-separated clauses AND together
    so ``">=0.1,<0.2"`` requires both.
    """
    declared = declared.strip()
    if declared == "*":
        return True
    target = _parse_version(version)
    for clause in declared.split(","):
        clause = clause.strip()
        if not clause:
            continue
        m = _RANGE_CLAUSE_RE.match(clause)
        if m is None:
            raise ValueError(f"not a parseable sdk_version clause: {clause!r}")
        op = m.group(1) or "=="
        bound = _parse_version(m.group(2))
        if op == ">=" and not (target >= bound):
            return False
        if op == ">" and not (target > bound):
            return False
        if op == "<=" and not (target <= bound):
            return False
        if op == "<" and not (target < bound):
            return False
        if op == "==" and target != bound:
            return False
    return True


def is_sdk_compatible(manifest: PluginManifest, *, running: str = SDK_VERSION) -> bool:
    """Return True iff the plugin's ``sdk_version`` range includes the running SDK."""
    return _in_range(manifest.sdk_version, running)


def assert_sdk_compatible(manifest: PluginManifest, *, running: str = SDK_VERSION) -> None:
    """Raise :class:`PluginSdkVersionMismatch` if the plugin is incompatible."""
    if not is_sdk_compatible(manifest, running=running):
        raise PluginSdkVersionMismatch(
            plugin_id=manifest.id,
            declared=manifest.sdk_version,
            running=running,
        )
