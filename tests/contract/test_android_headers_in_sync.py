"""Cross-repo contract guard: the Android header-manifest mirror must equal
``contracts/ios-headers.json``.

The header manifest is SHARED verbatim between clients — both apps emit the
exact same 14-header set, so there is exactly one manifest (the ``ios-`` in
the filename is historical; renaming it would break the byte-pinned iOS
mirror for cosmetics). The Android repo carries a byte-for-byte mirror that
``HeaderContractTest.kt`` asserts the app's real upload request emits exactly.

Skipped when the Android repo isn't checked out alongside datahub; runs in
the product workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_MANIFEST = REPO_ROOT / "contracts" / "ios-headers.json"
ANDROID_MANIFEST = (
    REPO_ROOT.parent
    / "android_app"
    / "contract"
    / "src"
    / "test"
    / "resources"
    / "fixtures"
    / "healthsave-headers.json"
)

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT.parent / "android_app").exists(),
    reason="Android app repo not checked out alongside datahub; run in the product workspace",
)


def test_header_manifest_matches_android_mirror() -> None:
    assert ANDROID_MANIFEST.exists(), (
        f"Android header-manifest mirror missing at {ANDROID_MANIFEST}. "
        "Copy it: cp contracts/ios-headers.json "
        "../android_app/contract/src/test/resources/fixtures/healthsave-headers.json"
    )
    dh = json.loads(DH_MANIFEST.read_text())
    android = json.loads(ANDROID_MANIFEST.read_text())
    assert dh == android, (
        "contract drift: contracts/ios-headers.json differs from the Android "
        "mirror. A header rename on either side is a client-breaking change — "
        "update the manifest, mirror it to BOTH clients, and coordinate the "
        "change deliberately."
    )
