"""Cross-repo contract guard: both clients' parity-manifest mirrors must equal
``contracts/parity.json``.

datahub is the canonical home (the workspace root is not a git repo, so it
cannot own version-controlled truth). Each client carries a byte-equal mirror
asserted by its own suite (iOS ``ParityManifestTests.swift``, Android
``ParityManifestTest.kt``). Editing the manifest without re-mirroring goes red
here, in trust-fast.

Each sibling skips independently when its repo isn't checked out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_MANIFEST = REPO_ROOT / "contracts" / "parity.json"

MIRRORS = {
    "ios_app": REPO_ROOT.parent
    / "ios_app"
    / "Tests"
    / "HealthSyncTests"
    / "Fixtures"
    / "parity.json",
    "android_app": REPO_ROOT.parent
    / "android_app"
    / "contract"
    / "src"
    / "test"
    / "resources"
    / "fixtures"
    / "parity.json",
}


@pytest.mark.parametrize("sibling", sorted(MIRRORS), ids=str)
def test_parity_manifest_matches_mirror(sibling: str) -> None:
    mirror = MIRRORS[sibling]
    if not (REPO_ROOT.parent / sibling).exists():
        pytest.skip(f"{sibling} not checked out alongside datahub")
    assert mirror.exists(), (
        f"parity manifest mirror missing at {mirror}. Copy it: cp contracts/parity.json {mirror}"
    )
    dh = json.loads(DH_MANIFEST.read_text())
    other = json.loads(mirror.read_text())
    assert dh == other, (
        f"parity manifest drift between datahub and {sibling}. "
        "contracts/parity.json is canonical — edit it there and re-copy the "
        "mirror into BOTH clients."
    )
