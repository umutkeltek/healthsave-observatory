"""v1 compatibility capsule.

Single home for everything that is part of the v1 wire contract:
the Pydantic models that describe v1 request/response shapes, the
frozen route inventory, and any helpers that exist purely to keep
v1 clients (HealthSave iOS, the health-data-to-mqtt community
bridge, Grafana datasource consumers) working.

**Freeze semantics — what "frozen" actually means here.**

The audit (Phase 5G) flagged that this package was extended after
its initial creation in Phase 2 — Phase 4C added
``GET /api/insights/runs`` to ``V1_ROUTES_FROZEN`` and added
``RunSummaryResponse`` + ``RunsListResponse`` models. That looked
like governance drift on the surface.

In practice the freeze is "no silent removal, no silent shape change"
— NOT "no additions ever." Adding a route to v1 is allowed under
this discipline:

  1. Regenerate ``contracts/openapi/v1.locked.json`` (Docker-pinned
     env via ``make regen-lock``).
  2. Add the route to ``V1_ROUTES_FROZEN`` in this file.
  3. If the route belongs in :data:`IOS_FROZEN_ROUTES` too (i.e.,
     the HealthSave iOS app calls it), coordinate an App Store
     release and document in ``contracts/IOS_CROSS_CHECK.md``.
  4. Commit message names the route, the iOS-coordination decision,
     and the lock-regen command used.

What is **not** allowed under the freeze:

  - Renaming a field on an existing model.
  - Dropping a route from ``V1_ROUTES_FROZEN``.
  - Changing the response shape of an existing route.
  - Relaxing a validator on a field iOS depends on.

Phase 4C followed steps (1)–(4): the lock was regenerated, the
route was added explicitly, the commit message names the rationale.
That is the canonical pattern for v1 surface extensions.

**Versioning intent.** When v2 contracts land in
``packages/py/contracts/``, the v1 vs v2 boundary becomes
structural — anything imported from ``compat_v1`` is v1-frozen
(under the discipline above); anything from ``contracts`` is v2.
The ``contract_tests in ``tests/contract/api_v1/`` and the OpenAPI
lock at ``contracts/openapi/v1.locked.json`` enforce both halves.
"""

from __future__ import annotations

# Routes the live v1 surface serves. Sourced from
# ``contracts/openapi/v1.locked.json`` and pinned by
# ``tests/contract/api_v1/test_v1_contract.py``.
V1_ROUTES_FROZEN: frozenset[str] = frozenset(
    {
        "GET /health",
        "GET /api/health",
        "GET /ready",
        "POST /api/apple/batch",
        "GET /api/apple/status",
        "GET /metrics",
        "GET /api/insights/latest",
        "GET /api/insights/daily",
        "GET /api/insights/weekly",
        "GET /api/insights/anomalies",
        "GET /api/insights/trends",
        "POST /api/insights/trigger",
        "GET /api/insights/runs",
    }
)

# The narrow subset HealthSave iOS calls. Removing any of these
# breaks the App Store binary immediately and requires a coordinated
# iOS release. See ``contracts/IOS_CROSS_CHECK.md``.
IOS_FROZEN_ROUTES: frozenset[str] = frozenset(
    {
        "POST /api/apple/batch",
        "GET /api/apple/status",
        "GET /api/health",
    }
)
