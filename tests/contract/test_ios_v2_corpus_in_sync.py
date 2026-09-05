"""Cross-repo contract guard: datahub's v2 Apple golden corpus equals the iOS
app's v2 request goldens, byte for byte.

The v2 wire (``POST /api/v2/apple/batch``, Plan 2026-09-03) is owned by the
iOS app: ``ios_app/Tests/HealthSyncTests/Fixtures/v2_health_data_hub_*_batch.json``
are the hand-maintained goldens (pinned by the iOS ``V2RequestCorpusTests``
against the real ``AppleSyncBatchPayload`` serializer). datahub mirrors them at
``tests/fixtures/apple_healthsave_v2/`` so the server-side replay
(``test_v2_requests_accepted.py``) and downstream operators building their own
ingest (Eric's longitudinal engine) read the exact bytes the app emits.

Law 3 (workspace CLAUDE.md): change the OWNER (iOS), then ``cp`` — never edit
the mirror by hand. Skipped when the iOS repo isn't checked out alongside
datahub (backend-only CI); runs in the product workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave_v2"
IOS_DIR = REPO_ROOT.parent / "ios_app" / "Tests" / "HealthSyncTests" / "Fixtures"

pytestmark = pytest.mark.skipif(
    not IOS_DIR.exists(),
    reason="iOS app repo not checked out alongside datahub; run in product workspace",
)

DH_NAMES = sorted(p.name for p in DH_DIR.glob("*_batch.json"))


def _ios_name(dh_name: str) -> str:
    return f"v2_health_data_hub_{dh_name}"


def test_v2_corpus_is_not_empty() -> None:
    assert DH_NAMES, "v2 corpus mirror is empty — copy the iOS goldens first"


@pytest.mark.parametrize("dh_name", DH_NAMES)
def test_v2_corpus_matches_ios_goldens_byte_for_byte(dh_name: str) -> None:
    ios_path = IOS_DIR / _ios_name(dh_name)
    assert ios_path.exists(), (
        f"{dh_name} has no iOS owner golden at {ios_path.name}. The v2 corpus is "
        "owned by ios_app — add the golden there, then cp it here."
    )
    assert (DH_DIR / dh_name).read_bytes() == ios_path.read_bytes(), (
        f"v2 corpus drift for {dh_name}: datahub mirror != iOS golden. Which side "
        "changed on purpose? Regenerate at the OWNER (ios_app) and cp the bytes here."
    )


def test_every_ios_v2_golden_is_mirrored() -> None:
    ios_names = sorted(p.name for p in IOS_DIR.glob("v2_health_data_hub_*_batch.json"))
    missing = [
        n for n in ios_names if not (DH_DIR / n.removeprefix("v2_health_data_hub_")).exists()
    ]
    assert not missing, f"iOS v2 goldens without a datahub mirror: {missing}"
