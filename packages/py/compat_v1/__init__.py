"""v1 compatibility capsule.

Single home for everything that is part of the v1 wire contract:
the Pydantic models that describe v1 request/response shapes, the
frozen route inventory, and any helpers that exist purely to keep
v1 clients (HealthSave iOS, the health-data-to-mqtt community
bridge, Grafana datasource consumers) working.

Anything in this package is **frozen**. Changing a field name,
dropping a model, or relaxing a validator is a v1 contract change
and must be reviewed alongside an iOS-app coordination plan. The
contract tests in ``tests/contract/api_v1/`` and the OpenAPI lock
at ``contracts/openapi/v1.locked.json`` enforce this.

When v2 contracts land in ``packages/py/contracts/``, the v1 vs v2
boundary becomes structural — anything imported from ``compat_v1``
is v1-frozen; anything from ``contracts`` is v2.
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
