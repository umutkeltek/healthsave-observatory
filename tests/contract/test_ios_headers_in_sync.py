"""Cross-repo contract guard: the iOS header-manifest mirror must equal
``contracts/ios-headers.json``.

Same pattern as ``test_ios_corpus_in_sync.py``: datahub's manifest is
canonical, the iOS repo carries a byte-for-byte mirror that
``HeaderContractTests.swift`` asserts the app's real upload request
emits exactly. Skipped when the iOS repo isn't checked out alongside
datahub; runs in the product workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_MANIFEST = REPO_ROOT / "contracts" / "ios-headers.json"
IOS_MANIFEST = (
    REPO_ROOT.parent / "ios_app" / "Tests" / "HealthSyncTests" / "Fixtures" / "ios-headers.json"
)

pytestmark = pytest.mark.skipif(
    not IOS_MANIFEST.parent.exists(),
    reason="iOS app repo not checked out alongside datahub; run in the product workspace",
)


def test_header_manifest_matches_ios_mirror() -> None:
    assert IOS_MANIFEST.exists(), (
        f"iOS header-manifest mirror missing at {IOS_MANIFEST}. "
        "Copy it: cp contracts/ios-headers.json "
        "../ios_app/Tests/HealthSyncTests/Fixtures/ios-headers.json"
    )
    dh = json.loads(DH_MANIFEST.read_text())
    ios = json.loads(IOS_MANIFEST.read_text())
    assert dh == ios, (
        "contract drift: contracts/ios-headers.json differs from the iOS "
        "mirror. A header rename on either side is an iOS-app-breaking "
        "change — update the manifest, mirror it, and coordinate the change "
        "deliberately."
    )
