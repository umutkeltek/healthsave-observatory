"""The Android golden request corpus is not just pinned — it is INGESTIBLE.

``test_android_corpus_in_sync.py`` proves the fixtures equal the Android app's
real wire output; this module proves the server actually accepts that output:
every fixture validates as a ``BatchPayload`` and replays through the live
``server.apple_batch`` handler to a processed receipt that echoes the identity
headers. A server change that starts rejecting the Android additive fields
(``client_platform``, ``client_schema_version``, ``bridge_install_id``,
per-sample ``provider_object_id`` / ``source_bundle_id`` / ``device_*``) fails
here instead of on a phone.

Unlike the sync tests, this runs WITHOUT the sibling repo checked out (e.g.
backend-only CI) — it reads datahub's own fixture mirror. It self-skips only
while the corpus hasn't been generated yet (pre-P1 bootstrap).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from compat_v1.models import BatchPayload  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "android_healthsave"

FIXTURE_NAMES = sorted(p.name for p in FIXTURES_DIR.glob("*.json"))

pytestmark = pytest.mark.skipif(
    not FIXTURE_NAMES,
    reason="Android request corpus not generated yet (pre-P1 bootstrap)",
)

# The frozen v1 top-level fields plus the recorded Android additive batch
# fields (endpoint-reuse decision, Android plan 2026-06-10). Additive-only:
# the v1 set may never shrink, and new fields land here deliberately.
V1_TOP_LEVEL_FIELDS = frozenset({"metric", "batch_index", "total_batches", "samples"})
ANDROID_ADDITIVE_FIELDS = frozenset(
    {"client_platform", "client_schema_version", "bridge_install_id"}
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _android_headers(name: str, payload: dict) -> dict[str, str]:
    """Identity + idempotency headers the way the Android wire layer sends them."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    payload_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    return {
        "Idempotency-Key": payload_hash,
        "X-HealthSave-Payload-Hash": payload_hash,
        "X-HealthSave-Sync-Run-ID": f"android-corpus-run-{name}",
        "X-HealthSave-Batch-ID": f"android-corpus-batch-{name}",
        "X-HealthSave-Metric": payload["metric"],
        "X-HealthSave-Batch-Index": str(payload["batch_index"]),
        "X-HealthSave-Total-Batches": str(payload["total_batches"]),
    }


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_carries_v1_and_android_identity_fields(name: str) -> None:
    raw = _load(name)
    missing_v1 = V1_TOP_LEVEL_FIELDS - set(raw)
    assert not missing_v1, f"{name} missing frozen v1 fields: {sorted(missing_v1)}"
    missing_android = ANDROID_ADDITIVE_FIELDS - set(raw)
    assert not missing_android, (
        f"{name} missing Android additive identity fields: {sorted(missing_android)}. "
        "Platform identity travels in payload fields, never in the route."
    )
    assert raw["client_platform"] == "android-health-connect"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_validates_as_batch_payload(name: str) -> None:
    """The additive fields must stay ignorable extras to the v1 model."""
    payload = BatchPayload.model_validate(_load(name))
    assert payload.samples, f"{name} has no samples"
    assert payload.total_batches >= 1
    for sample in payload.samples:
        assert any(k in sample for k in ("date", "startDate", "start", "start_date")), (
            f"{name} sample missing a time key: {sample}"
        )
        assert any(k in sample for k in ("qty", "value", "total_energy", "duration")), (
            f"{name} sample missing a value key: {sample}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FIXTURE_NAMES)
async def test_fixture_replays_to_processed_receipt(name: str) -> None:
    """Every corpus request goes through the LIVE handler to a receipt."""
    import server

    from tests.test_api_contract import FakeRequest, FakeSession

    payload = _load(name)
    headers = _android_headers(name, payload)
    session = FakeSession()

    result = await server.apple_batch(FakeRequest(payload, headers=headers), session)

    assert result["status"] == "processed", f"{name}: not processed: {result}"
    assert result["sync_run_id"] == headers["X-HealthSave-Sync-Run-ID"]
    assert result["idempotency_key"] == headers["Idempotency-Key"]
    assert result["metric"] == payload["metric"]
    assert result["records_received"] == len(payload["samples"])
    # Aggregating parsers may legitimately collapse samples (e.g. sleep stages
    # → one session), so accepted can be < received — but REJECTING any Android
    # corpus sample is a contract break.
    assert result["records_rejected"] == 0, (
        f"{name}: the server rejected Android corpus samples: {result}"
    )
    assert result["records_accepted"] >= 1, f"{name}: nothing accepted: {result}"

    receipt = session.insert_params_for("healthsave_sync_receipts")
    assert receipt is not None, f"{name}: no sync receipt row recorded"
    assert receipt["sync_run_id"] == headers["X-HealthSave-Sync-Run-ID"]
    assert receipt["payload_hash"] == headers["X-HealthSave-Payload-Hash"]
