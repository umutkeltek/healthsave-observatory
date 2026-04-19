"""Unit tests for :class:`analysis.statistical.anomaly.AnomalyDetector`.

Follows the Phase 1/1.5 ``FakeSession`` discipline — no live DB. Each
test queues a sequence of pre-canned rowsets keyed by the order in
which the detector executes its SQL queries (HR obs → HR baseline →
HRV obs → HRV baseline → workouts). Severity tiering, context
filtering, and the data-sufficiency gate all exercise here.
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
    """Lightweight row stub — attribute access mimics SQLAlchemy ``Row``."""


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Queues batches of rows, one batch per ``execute`` call."""

    def __init__(self, batches):
        self._batches = list(batches)
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        rows = self._batches.pop(0) if self._batches else []
        return _Result(rows)


def _session_factory(batches):
    """Build a callable that returns a prepared FakeSession instance."""
    session = _FakeSession(batches)

    def factory():
        return session

    factory.session = session
    return factory


def _config(sensitivity: str = "normal") -> AnalysisConfig:
    return AnalysisConfig.model_validate(
        {"analysis": {"anomaly_detection": {"enabled": True, "sensitivity": sensitivity}}}
    )


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

    # HRV obs empty, HRV baseline empty, workouts empty.
    session_factory = _session_factory([hr_obs, baseline, [], [], []])

    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.metric == "heart_rate"
    assert a.direction == "up"
    # 120 vs mean ~65.5 sigma ~0.4 → z >> 3.0 → alert
    assert a.severity == "alert"
    assert a.magnitude > 3.0


# ──────────────────────────────────────────────────────────────
#  Severity tiering — each band
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_tiers_severity_info_watch_alert_for_normal_sensitivity():
    """info (2.0-2.5), watch (2.5-3.0), alert (>=3.0)."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)

    # Baseline: mean=100, stddev ≈ 10 (engineered via a small sample).
    # Using values 90, 100, 110 repeated gives mean=100, stdev ≈ 10.
    baseline_values = [90.0, 100.0, 110.0] * 10
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=v)
        for i, v in enumerate(baseline_values)
    ]

    # Three observations — expected z-scores ≈ 2.17, 2.65, 3.61 → info, watch, alert.
    # (baseline stddev ≈ 8.305)
    hr_obs = [
        _Row(bucket=obs_time, value=118.0),  # z ≈ 2.17 → info
        _Row(bucket=obs_time - timedelta(hours=1), value=122.0),  # z ≈ 2.65 → watch
        _Row(bucket=obs_time - timedelta(hours=2), value=130.0),  # z ≈ 3.61 → alert
    ]

    session_factory = _session_factory([hr_obs, baseline, [], [], []])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    severities = sorted(a.severity for a in anomalies)
    assert severities == ["alert", "info", "watch"]


# ──────────────────────────────────────────────────────────────
#  Sensitivity floors — low raises floor, high lowers it
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_low_sensitivity_raises_floor_to_2_5_sigma():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=v)
        for i, v in enumerate([90.0, 100.0, 110.0] * 10)
    ]
    # z ≈ 2.17 observation — above 2.0 floor, below 2.5 floor; suppressed at low sensitivity.
    hr_obs = [_Row(bucket=obs_time, value=118.0)]
    session_factory = _session_factory([hr_obs, baseline, [], [], []])
    detector = AnomalyDetector(session_factory, _config("low"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_detect_high_sensitivity_lowers_floor_to_1_5_sigma():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=v)
        for i, v in enumerate([90.0, 100.0, 110.0] * 10)
    ]
    # z ≈ 1.6 — suppressed at normal but surfaces at high.
    hr_obs = [_Row(bucket=obs_time, value=116.0)]
    session_factory = _session_factory([hr_obs, baseline, [], [], []])
    detector = AnomalyDetector(session_factory, _config("high"))
    anomalies = await detector.detect(lookback_days=1)
    assert len(anomalies) == 1
    assert anomalies[0].severity == "info"


# ──────────────────────────────────────────────────────────────
#  Data-sufficiency gate — thin baseline short-circuits
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_skips_when_baseline_has_too_few_observations():
    """Baseline below ``min_observations=14`` → empty result, no exception."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=200.0)]  # wild spike
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=65.0) for i in range(5)
    ]  # only 5 rows

    session_factory = _session_factory([hr_obs, baseline, [], [], []])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


# ──────────────────────────────────────────────────────────────
#  HRV detection — same machinery, different metric name
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_flags_hrv_drop_as_anomaly():
    """HRV anomalies use the ``hrv`` raw table and ``down`` direction."""
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    # Baseline HRV: tight around 50 ms.
    baseline = [
        _Row(time=obs_time - timedelta(hours=i + 1), value=50.0 + (i % 3) * 0.5) for i in range(30)
    ]
    # Observation: huge drop to 10 ms.
    hrv_obs = [_Row(time=obs_time, value=10.0)]

    # HR obs empty, HR baseline empty (so no HR detector run).
    session_factory = _session_factory([[], [], hrv_obs, baseline, []])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    assert anomalies[0].metric == "hrv"
    assert anomalies[0].direction == "down"
    assert anomalies[0].magnitude < -2.0


# ──────────────────────────────────────────────────────────────
#  Context filter — workout drops HR-up, sleep drops HR-down
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_filter_drops_heart_rate_spike_during_workout():
    obs_time = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
    hr_obs = [_Row(bucket=obs_time, value=150.0)]
    baseline = [
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=65.0 + (i % 3) * 0.5)
        for i in range(30)
    ]
    workout = [
        _Row(
            start_time=obs_time - timedelta(minutes=10),
            end_time=obs_time + timedelta(minutes=20),
        )
    ]

    # Query order: HR obs → HR baseline → HRV obs → workouts (HRV baseline
    # is skipped when HRV obs is empty).
    session_factory = _session_factory([hr_obs, baseline, [], workout])
    detector = AnomalyDetector(session_factory, _config("normal"))
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
        _Row(bucket=obs_time - timedelta(hours=i + 1), value=65.0 + (i % 3) * 0.5)
        for i in range(30)
    ]

    # No workouts needed — sleep-window rule runs on the anomaly timestamp alone.
    session_factory = _session_factory([hr_obs, baseline, [], [], []])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []


@pytest.mark.asyncio
async def test_context_filter_downgrades_hrv_drop_shortly_after_workout():
    # HRV anomaly at 13:30 UTC; workout ended at 12:30 UTC. Within 4h post-workout → downgrade.
    obs_time = datetime(2025, 1, 15, 13, 30, tzinfo=UTC)
    hrv_obs = [_Row(time=obs_time, value=10.0)]
    # Baseline engineered so z is large negative → would normally be 'alert'.
    baseline = [
        _Row(time=obs_time - timedelta(hours=i + 1), value=50.0 + (i % 3) * 0.5) for i in range(30)
    ]
    workout = [
        _Row(
            start_time=obs_time - timedelta(hours=2),
            end_time=obs_time - timedelta(hours=1),
        )
    ]

    session_factory = _session_factory([[], [], hrv_obs, baseline, workout])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)

    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.metric == "hrv"
    assert a.direction == "down"
    # Downgraded — regardless of raw magnitude, severity is info.
    assert a.severity == "info"


# ──────────────────────────────────────────────────────────────
#  Empty data path
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_returns_empty_when_no_observations_or_baseline():
    session_factory = _session_factory([[], [], [], [], []])
    detector = AnomalyDetector(session_factory, _config("normal"))
    anomalies = await detector.detect(lookback_days=1)
    assert anomalies == []
