"""Anomaly detection — z-score deviation from a 30-day personal baseline.

Phase 2 scope covers two metrics:

* ``heart_rate`` — hourly aggregates over yesterday vs hourly
  distribution over the preceding 30 days. Uses ``hr_hourly`` with a raw
  ``heart_rate`` fallback that mirrors
  :class:`~analysis.statistical.aggregator.DataAggregator`.
* ``hrv`` — raw rows in the ``hrv`` hypertable, since Apple Watch only
  records ~5-30 HRV samples per day and no continuous aggregate exists.

Both metrics go through the same z-score machinery: compute
``z = (x - baseline_mean) / baseline_stddev`` per observation in the
lookback window, flag anything with ``|z| >= threshold``. Threshold
scales with ``AnomalyConfig.sensitivity`` (low/normal/high).

Context filtering runs after detection to suppress physiologically
explainable anomalies:

* HR spikes during a logged ``workouts`` row → drop.
* HR drops during the sleep window (23:00-07:00) → drop.
* HRV drops within 4h of a workout end → downgrade from
  watch/alert to info.

The detector never raises from SQL errors — the engine wraps its
call-site in best-effort logic so a missing ``hrv`` row or an empty
workouts table can't fail the daily briefing.
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from ..types import Anomaly, Sensitivity, Severity
from .gates import MINIMUM_DATA_REQUIREMENTS

log = logging.getLogger("healthsave.analysis")


# Sensitivity → z-score floor (below this, nothing is flagged).
# `normal` is the literature-standard 2-sigma cutoff; `low` is the
# conservative "only wake me up for something dramatic" tier; `high`
# surfaces smaller deviations for power users watching a trend.
_SENSITIVITY_FLOOR: dict[Sensitivity, float] = {
    "low": 2.5,
    "normal": 2.0,
    "high": 1.5,
}

# Severity tier boundaries above the sensitivity floor.
_WATCH_Z = 2.5
_ALERT_Z = 3.0

# Context-filter windows (D6/D7 in the PRD).
_POST_WORKOUT_WINDOW = timedelta(hours=4)
_SLEEP_START_HOUR = 23
_SLEEP_END_HOUR = 7


def _severity_for(z: float, threshold: float) -> Severity | None:
    """Tier a z-score into ``info``/``watch``/``alert`` or suppress it.

    Below ``threshold`` → None (suppressed). Tier boundaries above the
    floor are fixed: ``[floor, _WATCH_Z) → info``, ``[_WATCH_Z, _ALERT_Z) → watch``,
    ``[_ALERT_Z, ∞) → alert``.
    """
    abs_z = abs(z)
    if abs_z < threshold:
        return None
    if abs_z < _WATCH_Z:
        return "info"
    if abs_z < _ALERT_Z:
        return "watch"
    return "alert"


class AnomalyDetector:
    """Detect statistically significant deviations from personal baseline."""

    def __init__(self, session_factory, config) -> None:
        """Store collaborators.

        ``config`` is the full :class:`~analysis.config.AnalysisConfig`.
        We read ``config.analysis.anomaly_detection.sensitivity`` to pick
        the z-score floor and ``config.analysis.daily_briefing.baseline_days``
        for the rolling-baseline window length.
        """
        self.session_factory = session_factory
        self.config = config

    @property
    def _threshold(self) -> float:
        sensitivity = self.config.analysis.anomaly_detection.sensitivity
        return _SENSITIVITY_FLOOR.get(sensitivity, 2.0)

    @property
    def _baseline_days(self) -> int:
        return self.config.analysis.daily_briefing.baseline_days

    async def detect(
        self, lookback_days: int = 1, *, end_at: datetime | None = None
    ) -> list[Anomaly]:
        """Return anomalies detected in the ``lookback_days`` window.

        By default the window ends at ``now`` so ad-hoc checks can catch
        fresh post-sync data. Callers that need a completed calendar day
        (daily briefing) pass ``end_at`` set to midnight UTC. Baseline is
        the ``baseline_days`` immediately preceding the lookback window.
        An empty list is the correct result when there is no data, not
        an error — the engine differentiates "nothing detected" from
        "detector crashed" via exception propagation.
        """
        end = end_at or datetime.now(tz=UTC)
        start = end - timedelta(days=lookback_days)
        baseline_start = start - timedelta(days=self._baseline_days)
        threshold = self._threshold

        async with self.session_factory() as session:
            hr = await self._zscore_anomalies(
                session,
                metric="heart_rate",
                fetcher=self._fetch_hr_observations,
                window_start=start,
                window_end=end,
                baseline_start=baseline_start,
                threshold=threshold,
            )
            hrv = await self._zscore_anomalies(
                session,
                metric="hrv",
                fetcher=self._fetch_hrv_observations,
                window_start=start,
                window_end=end,
                baseline_start=baseline_start,
                threshold=threshold,
            )
            raw = hr + hrv
            if not raw:
                return []
            filtered = await self._filter_context(session, raw)
        return filtered

    async def _zscore_anomalies(
        self,
        session,
        *,
        metric: str,
        fetcher,
        window_start: datetime,
        window_end: datetime,
        baseline_start: datetime,
        threshold: float,
    ) -> list[Anomaly]:
        """Shared z-score loop for a single metric.

        ``fetcher`` is an async callable returning ``[(timestamp, value), ...]``
        for a given window; HR and HRV differ only in which table they
        hit, so the z-score machinery is identical.
        """
        observations = await fetcher(session, window_start, window_end)
        if not observations:
            return []

        baseline_samples = await fetcher(session, baseline_start, window_start)
        if not self._has_sufficient_baseline(baseline_samples):
            return []

        mean, stddev = self._mean_stddev(baseline_samples)
        if stddev == 0:
            return []

        anomalies: list[Anomaly] = []
        for obs_time, value in observations:
            z = (value - mean) / stddev
            severity = _severity_for(z, threshold)
            if severity is None:
                continue
            anomalies.append(
                Anomaly(
                    metric=metric,
                    magnitude=z,
                    direction="up" if z > 0 else "down",
                    severity=severity,
                    detected_at=obs_time,
                    context={"value": value, "baseline_mean": mean, "baseline_stddev": stddev},
                )
            )
        return anomalies

    # ──────────────────────────────────────────────────────────────
    #  Observation fetches
    # ──────────────────────────────────────────────────────────────

    async def _fetch_hr_observations(
        self, session, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Return ``(bucket, avg_bpm)`` pairs from ``hr_hourly``.

        Falls back to aggregating raw ``heart_rate`` into 1-hour buckets
        when ``hr_hourly`` is empty (mirrors the aggregator's fallback
        so the detector stays usable on fresh installs).
        """
        result = await session.execute(
            text(
                """
                SELECT bucket, avg_bpm::float AS value
                FROM hr_hourly
                WHERE bucket >= :start AND bucket < :end
                  AND avg_bpm IS NOT NULL
                ORDER BY bucket ASC
                """
            ),
            {"start": start, "end": end},
        )
        rows = self._fetchall(result)
        if rows:
            return [(row.bucket, float(row.value)) for row in rows if row.value is not None]

        # Fallback: raw hypertable bucketed into hourly averages.
        result = await session.execute(
            text(
                """
                SELECT date_trunc('hour', time) AS bucket,
                       avg(bpm)::float AS value
                FROM heart_rate
                WHERE time >= :start AND time < :end
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            ),
            {"start": start, "end": end},
        )
        rows = self._fetchall(result)
        return [(row.bucket, float(row.value)) for row in rows if row.value is not None]

    async def _fetch_hrv_observations(
        self, session, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Return ``(time, value_ms)`` pairs from the raw ``hrv`` hypertable."""
        result = await session.execute(
            text(
                """
                SELECT time, value_ms::float AS value
                FROM hrv
                WHERE time >= :start AND time < :end
                ORDER BY time ASC
                """
            ),
            {"start": start, "end": end},
        )
        rows = self._fetchall(result)
        return [(row.time, float(row.value)) for row in rows if row.value is not None]

    # ──────────────────────────────────────────────────────────────
    #  Context filter
    # ──────────────────────────────────────────────────────────────

    async def _filter_context(self, session, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Drop or downgrade anomalies with an obvious physiological cause.

        * HR spike during a logged workout → drop.
        * HR drop during sleep window (23:00-07:00) → drop.
        * HRV drop within 4h of a workout end → downgrade severity.
        """
        times = [a.detected_at for a in anomalies if a.detected_at is not None]
        if not times:
            return anomalies

        min_t = min(times) - _POST_WORKOUT_WINDOW
        max_t = max(times)
        workouts = await self._fetch_workouts(session, min_t, max_t)

        kept: list[Anomaly] = []
        for anomaly in anomalies:
            detected = anomaly.detected_at
            if detected is None:
                kept.append(anomaly)
                continue

            # Rule 1: HR-up during a workout → drop.
            if (
                anomaly.metric == "heart_rate"
                and anomaly.direction == "up"
                and any(w["start"] <= detected <= w["end"] for w in workouts)
            ):
                continue

            # Rule 2: HR-down during sleep window → drop.
            if (
                anomaly.metric == "heart_rate"
                and anomaly.direction == "down"
                and self._in_sleep_window(detected)
            ):
                continue

            # Rule 3: HRV-down within the post-workout window → downgrade.
            if anomaly.metric == "hrv" and anomaly.direction == "down":
                recent_workout = any(
                    w["end"] <= detected <= w["end"] + _POST_WORKOUT_WINDOW for w in workouts
                )
                if recent_workout and anomaly.severity in ("watch", "alert"):
                    # Record why we downgraded so the API/LLM can explain it.
                    downgrade_context = {
                        **anomaly.context,
                        "downgrade_reason": "post_workout",
                    }
                    anomaly = anomaly.model_copy(
                        update={"severity": "info", "context": downgrade_context}
                    )

            kept.append(anomaly)
        return kept

    async def _fetch_workouts(
        self, session, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Return ``[{start, end}, ...]`` for workouts overlapping the window."""
        result = await session.execute(
            text(
                """
                SELECT start_time, end_time
                FROM workouts
                WHERE start_time <= :end AND end_time >= :start
                ORDER BY start_time ASC
                """
            ),
            {"start": start, "end": end},
        )
        rows = self._fetchall(result)
        return [
            {"start": row.start_time, "end": row.end_time}
            for row in rows
            if row.start_time is not None and row.end_time is not None
        ]

    # ──────────────────────────────────────────────────────────────
    #  Internals
    # ──────────────────────────────────────────────────────────────

    def _has_sufficient_baseline(self, samples: list[tuple[datetime, float]]) -> bool:
        """Enforce the Phase 2 data-sufficiency gate on the baseline."""
        requirements = MINIMUM_DATA_REQUIREMENTS["anomaly_detection"]
        minimum_observations = int(requirements["min_observations"])
        minimum_days = int(requirements["min_days"])
        days_with_data = {sample_time.date() for sample_time, _ in samples}
        return len(samples) >= minimum_observations and len(days_with_data) >= minimum_days

    @staticmethod
    def _mean_stddev(samples: list[tuple[datetime, float]]) -> tuple[float, float]:
        """Compute population mean + sample stddev of the value column."""
        values = [value for _, value in samples]
        mean = statistics.fmean(values)
        stddev = statistics.stdev(values) if len(values) > 1 else 0.0
        return mean, stddev

    @staticmethod
    def _in_sleep_window(when: datetime) -> bool:
        """True when ``when`` falls in the nightly sleep window."""
        hour = when.hour
        return hour >= _SLEEP_START_HOUR or hour < _SLEEP_END_HOUR

    @staticmethod
    def _fetchall(result) -> list[Any]:
        """Materialise a SQLAlchemy result set into a list (test-friendly).

        Real ``sqlalchemy.engine.Result`` supports ``.fetchall()``. Some
        test fakes only expose iteration — so we fall back to ``list(result)``
        when ``fetchall`` is absent.
        """
        fetchall = getattr(result, "fetchall", None)
        if callable(fetchall):
            rows = fetchall()
            return list(rows) if rows is not None else []
        try:
            return list(result)
        except TypeError:
            return []
