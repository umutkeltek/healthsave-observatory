"""Golden HealthSave/Apple v1 payload corpus — freeze + replay seed.

These fixtures are the exact ``POST /api/apple/batch`` bodies the HealthSave
iOS app sends. Pinning them here means a refactor that breaks the inbound
wire shape fails loudly. They are also the device-free fixture set Phase 1's
canonical normalizer maps and replays against (Decision H).

Corpus + rationale: ``tests/fixtures/apple_healthsave/README.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from compat_v1.models import BatchPayload

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "apple_healthsave"

# fixture filename -> the metric it must carry
EXPECTED: dict[str, str] = {
    "heart_rate_batch.json": "heart_rate",
    "sleep_analysis_batch.json": "sleep_analysis",
    "quantity_step_count_batch.json": "step_count",
    "workout_batch.json": "workouts",
}

# The top-level fields the iOS app puts on every batch (see
# test_v1_ios_contract.py::IOS_BATCH_PAYLOAD_FIELDS).
IOS_TOP_LEVEL_FIELDS = frozenset({"metric", "batch_index", "total_batches", "samples"})


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def test_corpus_is_complete() -> None:
    """No fixture may silently disappear from the golden corpus."""
    present = {p.name for p in FIXTURES_DIR.glob("*.json")}
    missing = set(EXPECTED) - present
    assert not missing, f"golden corpus missing fixtures: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_has_ios_top_level_fields(name: str) -> None:
    raw = _load(name)
    missing = IOS_TOP_LEVEL_FIELDS - set(raw)
    assert not missing, f"{name} missing iOS-frozen top-level fields: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_validates_as_batch_payload(name: str) -> None:
    payload = BatchPayload.model_validate(_load(name))
    assert payload.metric == EXPECTED[name]
    assert payload.samples, f"{name} has no samples"
    assert payload.total_batches >= 1
    # Every sample carries a time-ish and a value-ish key the parsers read via
    # first_present(...). This pins the wire reality, not a tidied-up shape.
    for sample in payload.samples:
        assert any(k in sample for k in ("date", "startDate", "start", "start_date")), (
            f"{name} sample missing a time key: {sample}"
        )
        assert any(k in sample for k in ("qty", "value", "total_energy", "duration")), (
            f"{name} sample missing a value key: {sample}"
        )
