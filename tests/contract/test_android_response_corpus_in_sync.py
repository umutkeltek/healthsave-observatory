"""Cross-repo contract guard: the Android response-fixture mirror must equal
datahub's golden response corpus.

The response corpus is SHARED between clients — the server emits identical
responses regardless of who posted the batch — so there is exactly one
generated corpus (``tests/fixtures/apple_healthsave_responses/``, datahub is
canonical, regenerated via ``make regen-response-corpus``) and each client
carries a byte-for-byte mirror. The Android mirror is decoded through the
app's real parsing paths by ``BackendResponseCorpusTest.kt``.

Skipped when the Android repo isn't checked out alongside datahub; runs in
the product workspace where both repos live side by side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave_responses"
ANDROID_DIR = (
    REPO_ROOT.parent
    / "android_app"
    / "contract"
    / "src"
    / "test"
    / "resources"
    / "fixtures"
    / "responses"
)

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT.parent / "android_app").exists(),
    reason="Android app repo not checked out alongside datahub; run in the product workspace",
)


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.json")}


def test_android_mirror_has_every_fixture() -> None:
    assert ANDROID_DIR.exists(), (
        f"Android response-fixture mirror missing at {ANDROID_DIR}. Copy the corpus: "
        "cp tests/fixtures/apple_healthsave_responses/*.json "
        "../android_app/contract/src/test/resources/fixtures/responses/"
    )
    missing = _names(DH_DIR) - _names(ANDROID_DIR)
    stale = _names(ANDROID_DIR) - _names(DH_DIR)
    assert not missing and not stale, (
        f"response corpus mirror out of sync: missing in Android {sorted(missing)}, "
        f"stale in Android {sorted(stale)}. datahub is the source of truth for "
        "responses — regenerate with `make regen-response-corpus` and copy the "
        "corpus into the Android mirror."
    )


@pytest.mark.parametrize(
    "name",
    sorted(p.name for p in DH_DIR.glob("*.json")),
)
def test_response_fixture_matches_android_mirror(name: str) -> None:
    dh = json.loads((DH_DIR / name).read_text())
    android = json.loads((ANDROID_DIR / name).read_text())
    assert dh == android, (
        f"contract drift: {name} differs between datahub and the Android mirror. "
        "datahub is the source of truth for responses — regenerate with "
        "`make regen-response-corpus` and copy the corpus into "
        "android_app/contract/src/test/resources/fixtures/responses/."
    )
