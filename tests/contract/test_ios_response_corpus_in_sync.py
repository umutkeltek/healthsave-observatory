"""Cross-repo contract guard: the iOS response-fixture mirror must equal
datahub's golden response corpus.

Counterpart of ``test_ios_corpus_in_sync.py`` with the direction
inverted: for *responses* the server is the wire source of truth (its
handlers emit them), so datahub's generated corpus
(``tests/fixtures/apple_healthsave_responses/``, see its README) is
canonical and the iOS repo carries a byte-for-byte mirror that
``BackendResponseCorpusTests.swift`` decodes through the app's real
parsing paths.

Skipped when the iOS repo isn't checked out alongside datahub (e.g.
backend-only CI); it runs in the product workspace where both repos
live side by side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave_responses"
IOS_DIR = REPO_ROOT.parent / "ios_app" / "Tests" / "HealthSyncTests" / "Fixtures" / "Responses"

pytestmark = pytest.mark.skipif(
    not IOS_DIR.parent.exists(),
    reason="iOS app repo not checked out alongside datahub; run in the product workspace",
)


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.json")}


def test_ios_mirror_has_every_fixture() -> None:
    assert IOS_DIR.exists(), (
        f"iOS response-fixture mirror missing at {IOS_DIR}. Copy the corpus: "
        "cp tests/fixtures/apple_healthsave_responses/*.json "
        "../ios_app/Tests/HealthSyncTests/Fixtures/Responses/"
    )
    missing = _names(DH_DIR) - _names(IOS_DIR)
    stale = _names(IOS_DIR) - _names(DH_DIR)
    assert not missing and not stale, (
        f"response corpus mirror out of sync: missing in iOS {sorted(missing)}, "
        f"stale in iOS {sorted(stale)}. datahub is the source of truth for "
        "responses — regenerate with `make regen-response-corpus` and copy the "
        "corpus into the iOS mirror."
    )


@pytest.mark.parametrize(
    "name",
    sorted(p.name for p in DH_DIR.glob("*.json")),
)
def test_response_fixture_matches_ios_mirror(name: str) -> None:
    dh = json.loads((DH_DIR / name).read_text())
    ios = json.loads((IOS_DIR / name).read_text())
    assert dh == ios, (
        f"contract drift: {name} differs between datahub and the iOS mirror. "
        "datahub is the source of truth for responses — regenerate with "
        "`make regen-response-corpus` and copy the corpus into "
        "ios_app/Tests/HealthSyncTests/Fixtures/Responses/."
    )
