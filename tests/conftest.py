"""Pytest session setup.

SECURITY-001 made the PHI surface default-deny: with no ``API_KEY`` and no
``ALLOW_NO_AUTH``, ``server.api.deps.verify_api_key`` now returns ``503`` instead
of serving open. The contract/integration suite intentionally exercises the
routes *keyless*, so we acknowledge open mode for the test session — the same
posture as local ``docker compose up``. Auth enforcement itself is covered by
``tests/test_auth.py``, which monkeypatches these flags per-test (and restores
them afterwards), so this global default does not weaken that coverage.
"""

from __future__ import annotations

import os

# Set the env var for any module that reads it at import time.
os.environ.setdefault("ALLOW_NO_AUTH", "true")

# Belt-and-suspenders: if deps was already imported (import order is not
# guaranteed across the suite), flip the live module global too. verify_api_key
# reads this global at call time, so this is sufficient on its own.
try:  # pragma: no cover - defensive
    from server.api import deps as _deps

    _deps.ALLOW_NO_AUTH = True
except Exception:  # noqa: BLE001 - deps may not be importable in every subset
    pass


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_v2_read_cache():
    """Reset the process-level SWR cache between tests.

    The v2 readiness/receipts routes cache the canonical-store aggregates;
    without this, one test's fake rows would leak into the next test's
    response. Cleared on both sides so test order never matters.
    """
    try:
        from server.api.swr import v2_read_cache
    except Exception:  # pragma: no cover - server may not import in every subset
        yield
        return
    v2_read_cache.clear()
    yield
    v2_read_cache.clear()
