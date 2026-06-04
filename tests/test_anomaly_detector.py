"""Unit tests for :class:`analysis.statistical.anomaly.AnomalyDetector`.

Follows the fake-data-source discipline - no live DB. Each test queues
pre-canned observation/workout batches behind the detector's injected read
interface. Severity tiering, context filtering, and the data-sufficiency gate
all exercise here.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import AnalysisConfig  # noqa: E402
from analysis.statistical.anomaly import AnomalyDetector  # noqa: E402


class _Row(SimpleNamespace):
    """Lightweight row stub - attribute access mimics SQLAlchemy ``Row``."""


def _observations(rows):
    observations = []
    for row in rows:
        if isinstance(row, tuple):
            observations.append(row)
            continue
        observed_at = getattr(row, "bucket", getattr(row, "time", None))
        observations.append((observed_at, row.value))
    return observations


def _workouts(rows):
    workouts = []
    for row in rows:
        if isinstance(row, dict):
            workouts.append(row)
            continue
        workouts.append({"start": row.start_time, "end": row.end_time})
    return workouts


class _AnomalyDataSource:
    def __init__(self, *, hr=None, hrv=None, workouts=None):
        self._hr_batches = list(hr or [])
        self._hrv_batches = list(hrv or [])
        self._workout_batches = list(workouts or [])
        self.hr_calls: list[tuple[datetime, datetime]] = []
        self.hrv_calls: list[tuple[datetime, datetime]] = []
        self.workout_calls: list[tuple[datetime, datetime]] = []

    async def fetch_hr_observations(self, start, end):
        self.hr_calls.append((start, end))
        rows = self._hr_batches.pop(0) if self._hr_batches else []
        return _observations(rows)

    async def fetch_hrv_observations(self, start, end):
        self.hrv_calls.append((start, end))
        rows = self._hrv_batches.pop(0) if self._hrv_batches else []
        return _observations(rows)

    async def fetch_workouts(self, start, end):
        self.workout_calls.append((start, end))
        rows = self._workout_batches.pop(0) if self._workout_batches else []
        return _workouts(rows)


def _config(sensitivity: str = "normal") -> AnalysisConfig:
    return AnalysisConfig.model_validate(
        {"analysis": {"anomaly_detection": {"enabled": True, "sensitivity": sensitivity}}}
    )


@pytest.mark.asyncio
async def test_detect_uses_injected_data_source_without_session():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    baseline = [(obs_time - timedelta(days=i + 1), 65.0 + (i % 3) * 0.5) for i in range(30)]

    class Source:
        def __init__(self):
            self.hr_calls: list[tuple[datetime, datetime]] = []

        async def fetch_hr_observations(self, start, end):
            self.hr_calls.append((start, end))
            return [(obs_time, 120.0)] if len(self.hr_calls) == 1 else baseline

        async def fetch_hrv_observations(self, start, end):
            return []

        async def fetch_workouts(self, start, end):
            return []

    source = Source()

    anomalies = await AnomalyDetector(source, _config("normal")).detect(lookback_days=1)

    assert len(anomalies) == 1
    assert anomalies[0].metric == "heart_rate"
    assert len(source.hr_calls) == 2


# ──────────────────────────────────────────────────────────────
#  Core happy-path: HR z-score detection flags a spike
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_flags_heart_rate_spike_with_normal_sensitivity():
    # Observation window: one outlier at 120 bpm, daytime (noon, not sleep window).
    # Use a past date outside the current date so window bounds don't reject it.
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=120.0)]

    # Baseline 30 observations tightly clustered around 65 bpm.
    baseline = [
        _Row(bucket=obs_time - timedelta(days=d, hours=1), value=65.0 + (d % 3) * 0.5)
        for d in range(30)
    ]

    # HRV obs empty, workouts empty.
    source = _AnomalyDataSource(hr=[hr_obs, baseline])

    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.metric == "heart_rate"
    assert a.direction == "up"
    # 120 vs mean ~65.5 sigma ~0.4 → z >> 3.0 → alert
    assert a.severity == "alert"
    assert a.magnitude > 3.0


# ──────────────────────────────────────────────────────────────
#  Severity tiering - each band
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_tiers_severity_info_watch_alert_for_normal_sensitivity():
    """info (2.0-2.5), watch (2.5-3.0), alert (>=3.0)."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)

    # Baseline: mean=100, stddev ≈ 10 (engineered via a small sample).
    # Using values 90, 100, 110 repeated gives mean=100, stdev ≈ 10.
    baseline_values = [90.0, 100.0, 110.0] * 10
    baseline = [
        _Row(bucket=obs_time - timedelta(days=i + 1), value=v)
        for i, v in enumerate(baseline_values)
    ]

    # Three observations - expected z-scores ≈ 2.17, 2.65, 3.61 → info, watch, alert.
    # (baseline stddev ≈ 8.305)
    hr_obs = [
        _Row(bucket=obs_time, value=118.0),  # z ≈ 2.17 → info
        _Row(bucket=obs_time - timedelta(hours=1), value=122.0),  # z ≈ 2.65 → watch
        _Row(bucket=obs_time - timedelta(hours=2), value=130.0),  # z ≈ 3.61 → alert
    ]

    source = _AnomalyDataSource(hr=[hr_obs, baseline])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    severities = sorted(a.severity for a in anomalies)
    assert severities == ["alert", "info", "watch"]


# ──────────────────────────────────────────────────────────────
#  Sensitivity floors - low raises floor, high lowers it
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_low_sensitivity_raises_floor_to_2_5_sigma():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    baseline = [
        _Row(bucket=obs_time - timedelta(days=i + 1), value=v)
        for i, v in enumerate([90.0, 100.0, 110.0] * 10)
    ]
    # z ≈ 2.17 observation - above 2.0 floor, below 2.5 floor; suppressed at low sensitivity.
    hr_obs = [_Row(bucket=obs_time, value=118.0)]
    source = _AnomalyDataSource(hr=[hr_obs, baseline])
    detector = AnomalyDetector(source, _config("low"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_detect_high_sensitivity_lowers_floor_to_1_5_sigma():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    baseline = [
        _Row(bucket=obs_time - timedelta(days=i + 1), value=v)
        for i, v in enumerate([90.0, 100.0, 110.0] * 10)
    ]
    # z ≈ 1.6 - suppressed at normal but surfaces at high.
    hr_obs = [_Row(bucket=obs_time, value=116.0)]
    source = _AnomalyDataSource(hr=[hr_obs, baseline])
    detector = AnomalyDetector(source, _config("high"))
    anomalies = await detector.detect(lookback_days=1)
    assert len(anomalies) == 1
    assert anomalies[0].severity == "info"


# ──────────────────────────────────────────────────────────────
#  Data-sufficiency gate - thin baseline short-circuits
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_skips_when_baseline_has_too_few_observations():
    """Baseline below ``min_observations=14`` → empty result, no exception."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=200.0)]  # wild spike
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=65.0) for i in range(5)
    ]  # only 5 rows

    source = _AnomalyDataSource(hr=[hr_obs, baseline])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_detect_skips_when_baseline_has_too_few_distinct_days():
    """Fourteen points on one day is not a mature 7-day baseline."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=130.0)]
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=65.0 + (i % 3) * 0.5)
        for i in range(14)
    ]

    source = _AnomalyDataSource(hr=[hr_obs, baseline])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_detect_can_scan_a_recent_rolling_window_instead_of_previous_midnight():
    """Ad-hoc anomaly checks need a fresh window ending at the supplied timestamp."""
    now = datetime(2026, 4, 19, 15, 30, tzinfo=UTC)
    source = _AnomalyDataSource(hr=[[]])
    detector = AnomalyDetector(source, _config("normal"))

    await detector.detect(lookback_days=1, end_at=now)

    start, end = source.hr_calls[0]
    assert end == now
    assert start == now - timedelta(days=1)


# ──────────────────────────────────────────────────────────────
#  HRV detection - same machinery, different metric name
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_flags_hrv_drop_as_anomaly():
    """HRV anomalies use the ``hrv`` raw table and ``down`` direction."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    # Baseline HRV: tight around 50 ms.
    baseline = [
        _Row(time=obs_time - timedelta(days=i + 1), value=50.0 + (i % 3) * 0.5) for i in range(30)
    ]
    # Observation: huge drop to 10 ms.
    hrv_obs = [_Row(time=obs_time, value=10.0)]

    # HR obs empty, HR baseline empty (so no HR baseline fetch).
    source = _AnomalyDataSource(hr=[[]], hrv=[hrv_obs, baseline])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    assert anomalies[0].metric == "hrv"
    assert anomalies[0].direction == "down"
    assert anomalies[0].magnitude < -2.0


# ──────────────────────────────────────────────────────────────
#  Context filter - workout drops HR-up, sleep drops HR-down
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_filter_drops_heart_rate_spike_during_workout():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=150.0)]
    baseline = [
        _Row(bucket=obs_time - timedelta(days=i + 1), value=65.0 + (i % 3) * 0.5) for i in range(30)
    ]
    workout = [
        _Row(
            start_time=obs_time - timedelta(minutes=10),
            end_time=obs_time + timedelta(minutes=20),
        )
    ]

    # HRV baseline is skipped when HRV obs is empty.
    source = _AnomalyDataSource(hr=[hr_obs, baseline], hrv=[[]], workouts=[workout])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    # HR-up during workout → dropped
    assert anomalies == []


@pytest.mark.asyncio
async def test_context_filter_drops_heart_rate_dip_during_sleep_window():
    # 03:00 UTC is deep in the 23-07 sleep window (D7).
    obs_time = datetime(2025, 1, 15, 3, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=40.0)]
    # Tight baseline around 65 bpm → z well below -2 for a value of 40.
    baseline = [
        _Row(bucket=obs_time - timedelta(days=i + 1), value=65.0 + (i % 3) * 0.5) for i in range(30)
    ]

    # No workouts needed - sleep-window rule runs on the anomaly timestamp alone.
    source = _AnomalyDataSource(hr=[hr_obs, baseline], hrv=[[]])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_context_filter_downgrades_hrv_drop_shortly_after_workout():
    # HRV anomaly at 13:30 UTC; workout ended at 12:30 UTC. Within 4h post-workout → downgrade.
    obs_time = datetime(2025, 1, 15, 13, 30, tzinfo=UTC)
    hrv_obs = [_Row(time=obs_time, value=10.0)]
    # Baseline engineered so z is large negative → would normally be 'alert'.
    baseline = [
        _Row(time=obs_time - timedelta(days=i + 1), value=50.0 + (i % 3) * 0.5) for i in range(30)
    ]
    workout = [
        _Row(
            start_time=obs_time - timedelta(hours=2),
            end_time=obs_time - timedelta(hours=1),
        )
    ]

    source = _AnomalyDataSource(hr=[[]], hrv=[hrv_obs, baseline], workouts=[workout])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.metric == "hrv"
    assert a.direction == "down"
    # Downgraded - regardless of raw magnitude, severity is info.
    assert a.severity == "info"


# ──────────────────────────────────────────────────────────────
#  Empty data path
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_returns_empty_when_no_observations_or_baseline():
    source = _AnomalyDataSource(hr=[[]], hrv=[[]])
    detector = AnomalyDetector(source, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []
