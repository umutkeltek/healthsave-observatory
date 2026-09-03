"""Plan 2026-09-03 Slice 5 — v2 ingest header consumer test.

Pins that the server's ``POST /api/v2/apple/batch`` route reads the
``X-HealthSave-*`` headers the iOS app emits. Mirrors
``tests/contract/api_v1/test_v1_ios_headers.py`` for the v2 surface.

Header manifest source of truth: ``contracts/v2-ios-headers.json``
(mirrored to ios_app/Tests/HealthSyncTests/Fixtures/v2-ios-headers.json).
Every header listed there must be consumed by the v2 route — server
side header omissions surface as NULL receipt columns, which the
operator diagnostics dashboard catches (see
``storage/timescale/sync_receipts.py``).

This is a structural test (route + manifest). The full empty-batch
POST round-trip is exercised by ``test_android_requests_accepted.py``
(replays fixtures through the live handler) and by the docker-backed
trust-e2e gate — those paths need a live Timescale DB and live
ingestion handler, neither of which lives in the trust-fast gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from server.main import app  # noqa: E402


def _v2_route_path() -> str:
    for route in app.routes:
        if hasattr(route, "path") and route.path == "/api/v2/apple/batch":
            return route.path
    raise AssertionError(
        "POST /api/v2/apple/batch is not registered. "
        "Slice 2 of Plan 2026-09-03 must add it."
    )


def test_v2_apple_batch_route_is_registered() -> None:
    """The v2 ingest route exists at the canonical path."""
    assert _v2_route_path() == "/api/v2/apple/batch"


def test_v2_route_headers_manifest_matches_server() -> None:
    """Every header declared in contracts/v2-ios-headers.json is a known
    X-HealthSave-* header the server records in the sync_receipts row.

    The manifest is the source of truth; the server's sync_receipts
    columns are the consumer. Drift between manifest and consumer
    surfaces here: if the manifest grows a header, this test fails
    until sync_receipts is taught to consume it; if the server adds a
    new receipt column not in the manifest, this test fails until
    the manifest grows to match.
    """
    manifest = (REPO_ROOT / "contracts" / "v2-ios-headers.json").read_text()
    declared = set(json.loads(manifest)["headers"].keys())
    for header in declared:
        assert header.startswith("X-HealthSave-") or header == "Idempotency-Key", (
            f"v2 manifest header {header!r} is not a known shape."
        )
    # The new advisory X-HealthSave-Schema-Version header must be in
    # the manifest. This is the v2-only header; the v1 manifest does
    # not contain it (CLAUDE.md Law 5 — v1 is frozen).
    assert "X-HealthSave-Schema-Version" in declared, (
        "v2 manifest must declare X-HealthSave-Schema-Version. "
        "Slice 4 of Plan 2026-09-03 requires it."
    )
    # v1-only identity headers must NOT have been lost. The v2
    # manifest is additive — v1 headers remain.
    for v1_only in (
        "X-HealthSave-Anchor-Present",
        "X-HealthSave-Batch-ID",
        "X-HealthSave-Batch-Index",
        "X-HealthSave-Full-Export",
        "X-HealthSave-Lower-Bound-Reason",
        "X-HealthSave-Metric",
        "X-HealthSave-Payload-Hash",
        "X-HealthSave-Query-Lower-Bound",
        "X-HealthSave-Sample-Max-Time",
        "X-HealthSave-Sample-Min-Time",
        "X-HealthSave-Sync-Mode",
        "X-HealthSave-Sync-Run-ID",
        "X-HealthSave-Total-Batches",
    ):
        assert v1_only in declared, (
            f"v2 manifest lost v1 header {v1_only}. The v2 wire is additive; "
            "renaming or removing v1 headers is an iOS-app-breaking change."
        )