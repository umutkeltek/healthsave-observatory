"""Whoop recovery back-fill: older per-metric rows -> the connector's own readings.

The back-fill must build exactly the observation the live connector writes for
the same recovery (same key, so nothing lands twice), send Whoop HRV to RMSSD
even when it sat in the SDNN ``hrv`` table, and skip values outside the
metric's range instead of guessing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID

from plugins.sources.whoop.normalize import (
    canonical_recovery_observations,
    whoop_stream_id,
)
from scripts.backfill_whoop_recovery import build_observations

RUN = UUID("00000000-0000-0000-0000-00000000b00f")
AT = datetime(2026, 11, 20, 6, 12, 44, 774000, tzinfo=UTC)


def test_legacy_rows_become_the_connectors_own_readings() -> None:
    rows = [
        (DEFAULT_OWNER_ID, "hrv_rmssd", AT, 71.2),  # from the SDNN-labelled hrv table
        (DEFAULT_OWNER_ID, "resting_heart_rate", AT, 52.0),
        (DEFAULT_OWNER_ID, "blood_oxygen", AT, 96.4),
    ]
    built, skipped = build_observations(rows, run_id=RUN)
    live = canonical_recovery_observations(
        [
            {
                "score_state": "SCORED",
                "created_at": "2026-11-20T06:12:44.774Z",
                "score": {
                    "hrv_rmssd_milli": 71.2,
                    "resting_heart_rate": 52,
                    "spo2_percentage": 96.4,
                },
            }
        ],
        owner_id=DEFAULT_OWNER_ID,
    )
    assert skipped == {}
    assert [o.metric_id for o in built] == [
        "vital.hrv_rmssd",
        "vital.resting_heart_rate",
        "vital.blood_oxygen",
    ]
    assert [o.dedup_key for o in built] == [o.dedup_key for o in live]
    assert {o.stream_id for o in built} == {whoop_stream_id(DEFAULT_OWNER_ID)}
    assert all(o.normalization_run_id == RUN for o in built)
    assert "vital.hrv_sdnn" not in {o.metric_id for o in built}


def test_a_fraction_spo2_is_read_as_percent_and_out_of_range_is_skipped() -> None:
    rows = [
        (DEFAULT_OWNER_ID, "blood_oxygen", AT, 0.97),
        (DEFAULT_OWNER_ID, "resting_heart_rate", AT, 400.0),
        (DEFAULT_OWNER_ID, "steps", AT, 1.0),
    ]
    built, skipped = build_observations(rows, run_id=RUN)
    assert [(o.metric_id, o.value.value) for o in built] == [("vital.blood_oxygen", 97.0)]
    assert skipped == {"out_of_range:vital.resting_heart_rate": 1, "unknown:steps": 1}


def test_each_owner_keeps_their_own_rows() -> None:
    other = UUID("7a1d2c3e-0000-4000-8000-0000000000aa")
    built, _ = build_observations(
        [(DEFAULT_OWNER_ID, "hrv_rmssd", AT, 60.0), (other, "hrv_rmssd", AT, 61.0)], run_id=RUN
    )
    assert [o.owner_id for o in built] == [DEFAULT_OWNER_ID, other]
    assert built[0].stream_id != built[1].stream_id
