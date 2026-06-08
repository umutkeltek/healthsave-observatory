# SPDX-License-Identifier: Apache-2.0
"""SDK version constant — the single source of truth for plugin
compatibility checks.

Every plugin declares an ``sdk_version`` semver range in its
``plugin.yaml``. The discovery layer rejects plugins whose declared
range does not include this constant. Bump on every breaking change
to the plugin contract (manifest schema, base-class signatures,
emit/consume taxonomy). Additive changes get a minor bump.

Phase 6 ships v0.1.0 — the contract is intentionally minimal so the
first third-party plugins can land before the surface freezes.
"""

from __future__ import annotations

SDK_VERSION = "0.1.0"
"""Semantic version of the live SDK contract. Bump on every breaking change."""

SDK_VERSION_TUPLE = (0, 1, 0)
"""Tuple form for callers that want a comparable identity."""
