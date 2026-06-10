"""Cross-repo contract guard: the datahub Android golden corpus must equal the
Android app's real output.

Counterpart of ``test_ios_corpus_in_sync.py`` for the second client. The
HealthSave Android app (``umutkeltek/healthsave-android``, workspace dir
``android_app/``) emits its request corpus from its real wire serializer
(``./gradlew :contract:regenRequestCorpus``); those fixtures are mirrored here
in ``tests/fixtures/android_healthsave/`` so the two repos can never silently
diverge. The Android repo is the wire source of truth for its own requests.

Skipped when the Android repo isn't checked out alongside datahub (e.g.
backend-only CI) or while the corpus hasn't been generated yet (pre-P1
bootstrap); it runs in the product workspace where both repos live side by side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_DIR = REPO_ROOT / "tests" / "fixtures" / "android_healthsave"
ANDROID_DIR = (
    REPO_ROOT.parent
    / "android_app"
    / "contract"
    / "src"
    / "test"
    / "resources"
    / "fixtures"
    / "requests"
)

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT.parent / "android_app").exists(),
    reason="Android app repo not checked out alongside datahub; run in the product workspace",
)


def _names(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    return {p.name for p in directory.glob("*.json")}


def test_android_corpus_dirs_in_sync() -> None:
    dh_names = _names(DH_DIR)
    android_names = _names(ANDROID_DIR)
    if not dh_names and not android_names:
        pytest.skip("Android request corpus not generated yet (pre-P1 bootstrap)")
    missing = android_names - dh_names
    stale = dh_names - android_names
    assert not missing and not stale, (
        f"request corpus mirror out of sync: missing in datahub {sorted(missing)}, "
        f"stale in datahub {sorted(stale)}. The Android app is the wire source of "
        "truth for its requests — regenerate with `./gradlew :contract:regenRequestCorpus` "
        "and copy the output into tests/fixtures/android_healthsave/."
    )


@pytest.mark.parametrize(
    "name",
    sorted(p.name for p in DH_DIR.glob("*.json")) if DH_DIR.exists() else [],
)
def test_corpus_matches_android_real_output(name: str) -> None:
    dh = json.loads((DH_DIR / name).read_text())
    android = json.loads((ANDROID_DIR / name).read_text())
    assert dh == android, (
        f"contract drift: {name} differs between datahub and the Android app. "
        "The Android app is the wire source of truth for its requests — re-sync "
        "datahub's corpus from it (regen + cp the Android fixture)."
    )
