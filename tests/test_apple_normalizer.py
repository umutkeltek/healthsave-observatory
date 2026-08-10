"""Apple Health -> canonical Observation normalizer, against the golden corpus."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, Provenance
from normalization import identity, normalize_apple_batch

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
    assert res.accepted == 1
    assert res.rejected == 0
    first = res.observations[0]
    assert first.metric_id == "vital.heart_rate"
    assert first.value.type == "quantity"
    assert first.value.value == 72.0
    assert first.value.canonical_unit == "bpm"
    assert first.interval_start == first.interval_end  # instant sample
    assert first.aggregation_scope == "interval_component"
    assert first.exact_ingest_key is None
    assert first.normalizer_id == "apple_health"
    assert len({o.dedup_key for o in res.observations}) == 1  # distinct samples


def test_sleep_batch_normalizes_to_categorical_intervals() -> None:
    res = _run("sleep_analysis_batch.json")
    assert res.accepted == 3
    assert res.rejected == 0
    assert all(o.metric_id == "sleep.stage" for o in res.observations)
    assert all(o.value.type == "categorical" for o in res.observations)
    assert {o.value.code for o in res.observations} <= {"awake", "rem", "core", "deep"}
    assert all(o.interval_start < o.interval_end for o in res.observations)  # ranged


def test_step_count_batch_maps_to_activity_steps() -> None:
    res = _run("quantity_step_count_batch.json")
    assert res.accepted == 1
    assert all(o.metric_id == "activity.steps" for o in res.observations)
    assert all(o.value.type == "quantity" for o in res.observations)


def test_healthkit_statistics_correction_keeps_one_stable_daily_identity() -> None:
    def normalize(qty: float):
        result = normalize_apple_batch(
            {
                "metric": "distance_walking_running",
                "samples": [
                    {
                        "date": "2026-08-09T04:00:00+00:00",
                        "qty": qty,
                        "source": "HealthKit Statistics",
                    }
                ],
            },
            source_id=_SOURCE,
            provenance=_PROV,
        )
        assert result.accepted == 1
        return result.observations[0]

    first = normalize(7_100.0)
    corrected = normalize(7_698.1)

    assert first.aggregation_scope == "owner_all_source_day_total"
    assert first.exact_ingest_key is not None
    assert corrected.exact_ingest_key == first.exact_ingest_key
    assert corrected.dedup_key == first.dedup_key
    assert corrected.interval_start == datetime(2026, 8, 9, 4, tzinfo=UTC)
    assert corrected.interval_end == corrected.interval_start


def test_healthkit_daily_identity_preserves_dst_midnights_and_separates_days() -> None:
    result = normalize_apple_batch(
        {
            "metric": "step_count",
            "samples": [
                {
                    "date": "2026-01-09T05:00:00+00:00",
                    "qty": 5_000,
                    "source": "HealthKit Statistics",
                },
                {
                    "date": "2026-08-09T04:00:00+00:00",
                    "qty": 6_000,
                    "source": "HealthKit Statistics",
                },
            ],
        },
        source_id=_SOURCE,
        provenance=_PROV,
    )

    assert [observation.interval_start.hour for observation in result.observations] == [5, 4]
    assert len({observation.dedup_key for observation in result.observations}) == 2


def test_healthkit_statistics_origin_uses_normalized_stream_identity() -> None:
    result = normalize_apple_batch(
        {
            "metric": "step_count",
            "samples": [
                {
                    "date": "2026-08-09T04:00:00+00:00",
                    "qty": 6_000,
                    "source": "  healthkit   STATISTICS  ",
                }
            ],
        },
        source_id=_SOURCE,
        provenance=_PROV,
    )

    observation = result.observations[0]
    assert observation.aggregation_scope == "owner_all_source_day_total"
    assert observation.exact_ingest_key is not None


def test_daily_metric_without_healthkit_statistics_origin_remains_component() -> None:
    result = normalize_apple_batch(
        {
            "metric": "step_count",
            "samples": [
                {
                    "date": "2026-08-09T04:00:00+00:00",
                    "qty": 10,
                    "source": "Apple Watch",
                }
            ],
        },
        source_id=_SOURCE,
        provenance=_PROV,
    )

    observation = result.observations[0]
    assert observation.aggregation_scope == "interval_component"
    assert observation.exact_ingest_key is None


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


def test_observation_carries_stream_id_matching_registry() -> None:
    # Each sample's origin must resolve to the same stream UUID the registry records,
    # so canonical_observations.stream_id == source_device_streams.id for that emitter.
    res = normalize_apple_batch(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 72, "source": "Apple Watch"}],
        },
        source_id=_SOURCE,
        provenance=_PROV,
    )
    assert res.accepted == 1
    obs = res.observations[0]
    expected = identity.resolve_apple_origin(DEFAULT_OWNER_ID, "Apple Watch").stream_id
    assert obs.stream_id == expected


def test_observation_without_source_gets_fallback_stream_id() -> None:
    # No source key -> the same fallback the registry uses (sample_device_name -> "HealthSave").
    res = normalize_apple_batch(
        {"metric": "heart_rate", "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 60}]},
        source_id=_SOURCE,
        provenance=_PROV,
    )
    assert res.accepted == 1
    obs = res.observations[0]
    expected = identity.resolve_apple_origin(DEFAULT_OWNER_ID, "HealthSave").stream_id
    assert obs.stream_id == expected


def test_unmapped_metric_rejects_every_sample() -> None:
    res = normalize_apple_batch(
        {"metric": "not_a_real_metric", "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 1}]},
        source_id=_SOURCE,
        provenance=_PROV,
    )
    assert res.accepted == 0
    assert res.rejected == 1
    assert res.rejections[0].reason.startswith("unmapped_metric")
