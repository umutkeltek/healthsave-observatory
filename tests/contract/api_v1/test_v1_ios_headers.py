"""HealthSave iOS wire-header contract for ``POST /api/apple/batch``.

The ``X-HealthSave-*`` headers (plus ``Idempotency-Key``) drive
idempotency, delivery receipts, and sample-window accounting. They were
previously documented only in prose (``contracts/IOS_CROSS_CHECK.md``);
this pins them to the manifest in ``contracts/ios-headers.json`` so a
rename on either side fails a test instead of silently breaking
duplicate-safe retry in production.

Three guards:

1. Manifest completeness — every ``X-HealthSave-*`` literal the ingest
   module reads appears in the manifest (and vice versa), so a header
   added or renamed server-side cannot bypass the contract.
2. Consumption — a golden batch sent with every manifest header is
   actually recorded: the receipt row echoes the identity headers and a
   reused key with a different payload hash is rejected with 409.
3. The iOS side mirrors the manifest byte-for-byte
   (``tests/contract/test_ios_headers_in_sync.py``) and asserts the app
   emits exactly these names (``HeaderContractTests.swift``).
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "contracts" / "ios-headers.json"

MANIFEST: dict[str, str] = json.loads(MANIFEST_PATH.read_text())["headers"]


def _golden_batch() -> dict:
    fixture = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave" / "heart_rate_batch.json"
    return json.loads(fixture.read_text())


def _manifest_request_headers() -> dict[str, str]:
    """One known value per manifest header, typed the way iOS sends them."""
    return {
        "Idempotency-Key": "sha256:manifest-payload",
        "X-HealthSave-Sync-Run-ID": "manifest-run-001",
        "X-HealthSave-Batch-ID": "manifest-batch-001",
        "X-HealthSave-Payload-Hash": "sha256:manifest-payload",
        "X-HealthSave-Metric": "heart_rate",
        "X-HealthSave-Batch-Index": "0",
        "X-HealthSave-Total-Batches": "1",
        "X-HealthSave-Sync-Mode": "incremental",
        "X-HealthSave-Anchor-Present": "true",
        "X-HealthSave-Lower-Bound-Reason": "anchor",
        "X-HealthSave-Full-Export": "false",
        "X-HealthSave-Query-Lower-Bound": "2026-01-01T00:00:00.000Z",
        "X-HealthSave-Sample-Min-Time": "2026-01-01T00:00:00.000Z",
        "X-HealthSave-Sample-Max-Time": "2026-01-01T06:00:00.000Z",
    }


def test_manifest_covers_request_helper() -> None:
    """The helper above must stay in lockstep with the manifest."""
    assert set(_manifest_request_headers()) == set(MANIFEST)


def test_manifest_is_complete_against_ingest_source() -> None:
    """Every X-HealthSave-* header the ingest module reads is in the manifest.

    Catches the silent failure mode where a server-side rename (or a new
    header) ships without updating the contract: the manifest, the iOS
    mirror, and the iOS emitter test must all move together.
    """
    from server.api import ingest

    source = inspect.getsource(ingest)
    read_headers = set(re.findall(r'"(X-HealthSave-[A-Za-z-]+)"', source))
    read_headers |= set(re.findall(r'"(Idempotency-Key)"', source))

    manifest_names = set(MANIFEST)
    unlisted = read_headers - manifest_names
    unread = manifest_names - read_headers
    assert not unlisted, (
        f"ingest reads headers missing from contracts/ios-headers.json: {sorted(unlisted)}. "
        "Add them to the manifest AND mirror to the iOS repo."
    )
    assert not unread, (
        f"manifest lists headers ingest no longer reads: {sorted(unread)}. "
        "If a header was renamed server-side, this is an iOS-app-breaking "
        "change — the shipped binary still sends the old name."
    )


@pytest.mark.asyncio
async def test_server_consumes_manifest_headers() -> None:
    """A batch sent with every manifest header is recorded faithfully."""
    import server

    from tests.test_api_contract import FakeRequest, FakeSession

    session = FakeSession()
    request = FakeRequest(_golden_batch(), headers=_manifest_request_headers())
    result = await server.apple_batch(request, session)

    receipt = session.insert_params_for("healthsave_sync_receipts")
    assert receipt is not None, "batch with manifest headers produced no sync receipt"
    assert receipt["sync_run_id"] == "manifest-run-001"
    assert receipt["batch_id"] == "manifest-batch-001"
    assert receipt["idempotency_key"] == "sha256:manifest-payload"
    assert receipt["payload_hash"] == "sha256:manifest-payload"
    assert receipt["sync_mode"] == "incremental"
    assert receipt["anchor_present"] is True
    assert receipt["lower_bound_reason"] == "anchor"
    assert receipt["full_export"] is False
    assert receipt["query_lower_bound_at"] is not None
    assert receipt["sample_min_at"] is not None
    assert receipt["sample_max_at"] is not None
    assert result["sync_run_id"] == "manifest-run-001"
    assert result["idempotency_key"] == "sha256:manifest-payload"


@pytest.mark.asyncio
async def test_reused_key_with_different_payload_is_rejected_409() -> None:
    """The idempotency headers must keep guarding duplicate-safe retry."""
    import server
    from fastapi import HTTPException

    from tests.test_api_contract import FakeRequest, FakeResult, FakeSession

    class ConflictSession(FakeSession):
        async def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            if sql.startswith("SELECT payload_hash FROM healthsave_sync_receipts"):
                self.calls.append((sql, params or {}))
                return FakeResult(row={"payload_hash": "sha256:a-different-payload"})
            return await super().execute(statement, params)

    request = FakeRequest(_golden_batch(), headers=_manifest_request_headers())
    with pytest.raises(HTTPException) as excinfo:
        await server.apple_batch(request, ConflictSession())
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error_code"] == "idempotency_key_payload_mismatch"
