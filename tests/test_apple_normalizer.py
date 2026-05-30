"""Apple Health -> canonical Observation normalizer, against the golden corpus."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from contracts._base import Provenance
from normalization import normalize_apple_batch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apple_healthsave"
_PROV = Provenance(
    source_plugin_id="apple_health",
    sdk_version="0.1.0",
    captured_at=datetime(2026, 5, 30, tzinfo=UTC),
)
_SOURCE = UUID("11111111-1111-1111-1111-111111111111")


def _run(name: str):
    payload = json.loads((FIXTURES / name).read_text())
    return normalize_apple_batch(payload, source_id=_SOURCE, provenance=_PROV)


def test_heart_rate_batch_normalizes_to_quantity_observations() -> None:
    res = _run("heart_rate_batch.json")
    assert res.accepted == 3
    assert res.rejected == 0
    first = res.observations[0]
    assert first.metric_id == "vital.heart_rate"
    assert first.value.type == "quantity"
    assert first.value.value == 61.0
    assert first.value.canonical_unit == "bpm"
    assert first.interval_start == first.interval_end  # instant sample
    assert first.normalizer_id == "apple_health"
    assert len({o.dedup_key for o in res.observations}) == 3  # distinct samples


def test_sleep_batch_normalizes_to_categorical_intervals() -> None:
    res = _run("sleep_analysis_batch.json")
    assert res.accepted == 4
    assert res.rejected == 0
    assert all(o.metric_id == "sleep.stage" for o in res.observations)
    assert all(o.value.type == "categorical" for o in res.observations)
    assert {o.value.code for o in res.observations} <= {"awake", "rem", "core", "deep"}
    assert all(o.interval_start < o.interval_end for o in res.observations)  # ranged


def test_step_count_batch_maps_to_activity_steps() -> None:
    res = _run("quantity_step_count_batch.json")
    assert res.accepted == 2
    assert all(o.metric_id == "activity.steps" for o in res.observations)
    assert all(o.value.type == "quantity" for o in res.observations)


def test_workout_batch_maps_to_event() -> None:
    res = _run("workout_batch.json")
    assert res.accepted == 1
    obs = res.observations[0]
    assert obs.metric_id == "workout.session"
    assert obs.value.type == "event"
    assert obs.interval_start < obs.interval_end


def test_sample_missing_time_is_rejected_not_dropped_silently() -> None:
    res = normalize_apple_batch(
        {"metric": "heart_rate", "samples": [{"qty": 60}]},
        source_id=_SOURCE,
        provenance=_PROV,
    )
    assert res.accepted == 0
    assert res.rejected == 1
    assert "time" in res.rejections[0].reason


def test_unmapped_metric_rejects_every_sample() -> None:
    res = normalize_apple_batch(
        {"metric": "not_a_real_metric", "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 1}]},
        source_id=_SOURCE,
        provenance=_PROV,
    )
    assert res.accepted == 0
    assert res.rejected == 1
    assert res.rejections[0].reason.startswith("unmapped_metric")
