"""Heartbeat series contract tests.

Pin the ``heartbeat_series`` wire metric (the beats behind an Apple Watch HRV
reading): the canonical store keeps every beat, the v1 writer counts instead of
rejecting, and both judge a sample by the same rule.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID, Provenance
from normalization.apple import normalize_apple_batch
from normalization.heartbeat import heartbeat_series_problem
from storage.timescale.measurements import _ingest_metric

GOLDEN = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "apple_healthsave_v2"
    / "heartbeat_series_batch.json"
)
_SOURCE = UUID("a9b1e7e0-0000-4000-8000-000000000002")


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        raise AssertionError("heartbeat series must not write to a v1 table")


def _series(**overrides):
    sample = {
        "uuid": "D2C70000-0000-4000-8000-0000000000C1",
        "startDate": "2026-08-30T07:12:00.000Z",
        "endDate": "2026-08-30T07:12:08.000Z",
        "tzOffsetMinutes": -240,
        "source": "Apple Watch",
        "heartbeats": [
            {"timeSinceStart": 0, "precededByGap": False},
            {"timeSinceStart": 0.9765625, "precededByGap": True},
        ],
    }
    sample.update(overrides)
    return sample


def _normalize(samples):
    return normalize_apple_batch(
        {"metric": "heartbeat_series", "samples": samples},
        source_id=_SOURCE,
        provenance=Provenance(
            source_plugin_id="apple-health-healthsave",
            sdk_version="test",
            captured_at=datetime.now(UTC),
        ),
        owner_id=DEFAULT_OWNER_ID,
    )


def test_golden_normalizes_every_series_with_every_beat() -> None:
    payload = json.loads(GOLDEN.read_text())
    result = _normalize(payload["samples"])

    assert result.rejected == 0, result.rejections
    assert result.accepted == len(payload["samples"])
    for observation, sample in zip(result.observations, payload["samples"], strict=True):
        assert observation.metric_id == "vital.heartbeat_series"
        assert observation.value.type == "event"
        assert observation.source_record_uid == sample["uuid"]
        # The beat list is the point of the metric: it must survive whole and in order.
        assert observation.value.summary["heartbeats"] == sample["heartbeats"]
        assert observation.value.summary.get("hrvUUID") == sample.get("hrvUUID")
        assert observation.interval_start < observation.interval_end


def test_golden_pins_a_gap_and_both_link_states() -> None:
    samples = json.loads(GOLDEN.read_text())["samples"]
    assert any(beat["precededByGap"] for sample in samples for beat in sample["heartbeats"])
    assert {("hrvUUID" in sample) for sample in samples} == {True, False}


@pytest.mark.asyncio
async def test_v1_writer_counts_series_without_writing_or_rejecting() -> None:
    session = _FakeSession()
    result = await _ingest_metric(session, 1, "heartbeat_series", [_series(), _series(uuid="x")])

    assert result.accepted == 2
    assert result.rejected == 0
    assert session.calls == []


@pytest.mark.asyncio
async def test_v1_writer_and_normalizer_reject_the_same_samples() -> None:
    bad = [
        _series(heartbeats=None),
        _series(heartbeats=[{"timeSinceStart": -1, "precededByGap": False}]),
        _series(heartbeats=[{"timeSinceStart": 1, "precededByGap": "no"}]),
        _series(startDate=None),
    ]
    stored = await _ingest_metric(_FakeSession(), 1, "heartbeat_series", [_series(), *bad])
    canonical = _normalize([_series(), *bad])

    assert (stored.accepted, stored.rejected) == (1, len(bad))
    assert (canonical.accepted, canonical.rejected) == (1, len(bad))


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"heartbeats": None}, "missing_heartbeats"),
        ({"heartbeats": "0.9,1.8"}, "missing_heartbeats"),
        ({"heartbeats": [0.9]}, "invalid_heartbeat"),
        ({"heartbeats": [{"precededByGap": False}]}, "invalid_heartbeat_offset"),
        (
            {"heartbeats": [{"timeSinceStart": True, "precededByGap": False}]},
            "invalid_heartbeat_offset",
        ),
        (
            {"heartbeats": [{"timeSinceStart": float("nan"), "precededByGap": False}]},
            "invalid_heartbeat_offset",
        ),
        (
            {"heartbeats": [{"timeSinceStart": -0.5, "precededByGap": False}]},
            "invalid_heartbeat_offset",
        ),
        ({"heartbeats": [{"timeSinceStart": 0.5}]}, "invalid_heartbeat_gap_flag"),
        (
            {"heartbeats": [{"timeSinceStart": 0.5, "precededByGap": 0}]},
            "invalid_heartbeat_gap_flag",
        ),
        ({"hrvUUID": "not-a-uuid"}, "invalid_hrv_uuid"),
        ({"hrvUUID": 7}, "invalid_hrv_uuid"),
        ({"startDate": "yesterday"}, "missing_or_unparseable_time"),
    ],
)
def test_rule_names_what_is_wrong(override, reason) -> None:
    assert heartbeat_series_problem(_series(**override)) == reason


def test_rule_accepts_an_empty_series_and_integer_offsets() -> None:
    # HealthKit can hold a series with no beats; it is still that series, not a bad sample.
    assert heartbeat_series_problem(_series(heartbeats=[])) is None
    assert (
        heartbeat_series_problem(
            _series(heartbeats=[{"timeSinceStart": 2, "precededByGap": False}])
        )
        is None
    )
    assert heartbeat_series_problem(_series(hrvUUID="D2C70000-0000-4000-8000-0000000000B1")) is None
