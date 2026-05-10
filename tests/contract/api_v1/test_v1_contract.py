"""v1 wire-format contract tests.

The HealthSave iOS app (App Store ID 6759843047) and other v1 clients
depend on a fixed set of routes and payload shapes. This test fails if
the live FastAPI app's OpenAPI schema diverges from
``contracts/openapi/v1.locked.json`` or if any route from the v1
inventory disappears.

Bump the lock deliberately via ``python -m scripts.generate_v1_lock`` —
never silently. A diff in the lock file is a v1 contract change and
must be reviewed alongside an iOS-app coordination note.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from compat_v1 import V1_ROUTES_FROZEN  # noqa: E402
from server.main import app  # noqa: E402

LOCK_PATH = REPO_ROOT / "contracts" / "openapi" / "v1.locked.json"

# FastAPI built-ins that aren't part of the v1 contract.
_FASTAPI_BUILTINS: frozenset[str] = frozenset(
    {
        "GET /docs",
        "GET /docs/oauth2-redirect",
        "GET /redoc",
        "GET /openapi.json",
    }
)


def _live_routes() -> frozenset[str]:
    out = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            out.add(f"{method} {path}")
    return frozenset(out)


def test_v1_routes_present() -> None:
    """Every frozen v1 route must still be served by the live app."""
    live = _live_routes()
    missing = V1_ROUTES_FROZEN - live
    assert not missing, (
        f"v1 contract break — missing routes: {sorted(missing)}. "
        "If a v1 route is being removed, that requires a deliberate "
        "iOS-coordinated deprecation, not a casual diff."
    )


def test_no_unexpected_v1_routes() -> None:
    """New top-level routes must extend V1_ROUTES_FROZEN deliberately."""
    live = _live_routes()
    unexpected = live - V1_ROUTES_FROZEN - _FASTAPI_BUILTINS
    assert not unexpected, (
        f"New routes detected outside the v1 frozen inventory: {sorted(unexpected)}. "
        "Add them to V1_ROUTES_FROZEN and regenerate the lock if intended."
    )


def test_openapi_matches_locked_snapshot() -> None:
    """Full OpenAPI schema must match the committed lock file."""
    if not LOCK_PATH.exists():
        pytest.skip(
            f"lock file not generated yet: {LOCK_PATH}. "
            "Run `python -m scripts.generate_v1_lock` to create it."
        )
    live = app.openapi()
    locked = json.loads(LOCK_PATH.read_text())
    assert live == locked, (
        "v1 OpenAPI drift detected. If the change is intentional, run "
        "`python -m scripts.generate_v1_lock` and commit the diff with "
        "an iOS-coordination note."
    )
