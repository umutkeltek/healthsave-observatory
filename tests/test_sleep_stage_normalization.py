"""Shared sleep-stage wire vocabulary normalization regressions for GH-20."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from contracts._base import Provenance
from normalization import NORMALIZER_VERSION, normalize_apple_batch

_SOURCE = UUID("11111111-1111-1111-1111-111111111111")
_PROVENANCE = Provenance(
    source_plugin_id="apple_health",
    sdk_version="0.2.0",
    captured_at=datetime(2026, 8, 10, tzinfo=UTC),
)


def test_shared_sleep_stage_values_normalize_as_ranged_categorical_observations() -> None:
    expected = [
        ("Asleep", "asleep"),
        ("Asleep Unspecified", "asleep"),
        ("In Bed", "in_bed"),
        ("Light", "light"),
        ("Unknown", "unknown"),
        ("HKCategoryValueSleepAnalysisAsleepUnspecified", "asleep"),
        ("HKCategoryValueSleepAnalysisInBed", "in_bed"),
    ]
    start = datetime(2026, 8, 9, 20, tzinfo=UTC)
    samples = [
        {
            "startDate": (start + timedelta(minutes=30 * index)).isoformat(),
            "endDate": (start + timedelta(minutes=30 * (index + 1))).isoformat(),
            "value": raw,
            "source": "Shared sleep fixture",
        }
        for index, (raw, _) in enumerate(expected)
    ]

    result = normalize_apple_batch(
        {"metric": "sleep_analysis", "samples": samples},
        source_id=_SOURCE,
        provenance=_PROVENANCE,
    )

    assert result.rejected == 0
    assert NORMALIZER_VERSION == "0.4.0"
    assert {observation.normalizer_version for observation in result.observations} == {"0.4.0"}
    assert [observation.value.code for observation in result.observations] == [
        code for _, code in expected
    ]
    assert all(
        observation.interval_start < observation.interval_end for observation in result.observations
    )
