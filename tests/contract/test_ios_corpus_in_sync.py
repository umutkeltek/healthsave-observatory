"""Cross-repo contract guard: the datahub Apple golden corpus must equal the
iOS app's real output.

The HealthSave iOS app (``umutkeltek/HealthSave``) is the frozen App Store
binary, so the batch payloads it emits *are* the wire contract. This pins
datahub's ``apple_healthsave`` corpus to those exact payloads so the two can
never silently diverge again — the drift that previously hid the sleep-stage
rejection bug (real ``Core/Deep/REM`` values vs a fictional lowercase fixture).

Skipped when the iOS repo isn't checked out alongside datahub (e.g. backend-only
CI); it runs in the product workspace where both repos live side by side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DH_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave"
IOS_DIR = REPO_ROOT.parent / "ios_app" / "Tests" / "HealthSyncTests" / "Fixtures"

# datahub fixture -> the iOS fixture it must match (the app's real output).
PAIRS = {
    "heart_rate_batch.json": "health_data_hub_heart_rate_batch.json",
    "sleep_analysis_batch.json": "health_data_hub_sleep_analysis_batch.json",
    "quantity_step_count_batch.json": "health_data_hub_step_count_batch.json",
    "workout_batch.json": "health_data_hub_workouts_batch.json",
}

pytestmark = pytest.mark.skipif(
    not IOS_DIR.exists(),
    reason="iOS app repo not checked out alongside datahub; run in the product workspace",
)


@pytest.mark.parametrize(("dh_name", "ios_name"), sorted(PAIRS.items()))
def test_corpus_matches_ios_real_output(dh_name: str, ios_name: str) -> None:
    dh = json.loads((DH_DIR / dh_name).read_text())
    ios = json.loads((IOS_DIR / ios_name).read_text())
    assert dh == ios, (
        f"contract drift: {dh_name} != iOS {ios_name}. The iOS app is the wire "
        "source of truth — re-sync datahub's corpus from it (cp the iOS fixture)."
    )
