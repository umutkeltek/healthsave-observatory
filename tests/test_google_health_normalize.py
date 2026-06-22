"""Google Health API data point normalizers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from plugins.sources.google_health.normalize import SOURCE_TAG, normalize_step_points  # noqa: E402


def test_normalize_step_points_emits_existing_step_count_metric_shape() -> None:
    out = normalize_step_points(
        [
            {
                "name": "users/me/dataTypes/steps/dataPoints/step-a",
                "dataSource": {
                    "device": {
                        "manufacturer": "Fitbit",
                        "displayName": "Fitbit Charge 6",
                    },
                    "application": {"packageName": "com.google.fitbit"},
                    "platform": "ANDROID",
                },
                "steps": {
                    "interval": {
                        "startTime": "2026-06-01T08:00:00Z",
                        "endTime": "2026-06-01T08:15:00Z",
                    },
                    "count": "42",
                },
            }
        ]
    )

    assert out == {
        "step_count": [
            {
                "date": "2026-06-01T08:00:00Z",
                "qty": 42.0,
                "unit": "count",
                "source": SOURCE_TAG,
                "provider_object_id": "users/me/dataTypes/steps/dataPoints/step-a",
                "provider_device_id": "Fitbit Charge 6",
                "origin_provider": "google-health-api",
                "source_application": "com.google.fitbit",
                "source_platform": "ANDROID",
            }
        ]
    }


def test_normalize_step_points_skips_rows_without_name_interval_or_count() -> None:
    out = normalize_step_points(
        [
            {"steps": {"interval": {"startTime": "2026-06-01T08:00:00Z"}, "count": "42"}},
            {"name": "missing-start", "steps": {"count": "42"}},
            {"name": "missing-count", "steps": {"interval": {"startTime": "2026-06-01T08:00:00Z"}}},
            {"name": "bad-count", "steps": {"interval": {"startTime": "2026-06-01T08:00:00Z"}, "count": "nope"}},
        ]
    )

    assert out == {"step_count": []}
