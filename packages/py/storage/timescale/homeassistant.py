"""Timescale read model for the Home Assistant MQTT bridge."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from homeassistant_mqtt.snapshot import (
    HealthSnapshot,
    SourceHealthSnapshot,
    derive_room_health_state,
    int_or_none,
    round_float,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _fresh_hours(name: str, default: int) -> int:
    """Freshness window (hours) for an HA read-model query, overridable via env.

    A health value older than the window reads as stale and the HA entity goes
    unavailable — correct by default. Widen only if a source syncs less often
    than the window and you'd rather surface the last value than 'unavailable'.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


# Defaults preserve prior behavior (aggregate latest HR 6h, per-source HR 72h).
_HR_FRESH_HOURS = _fresh_hours("HA_MQTT_HR_FRESH_HOURS", 6)
_SOURCE_HR_FRESH_HOURS = _fresh_hours("HA_MQTT_SOURCE_HR_FRESH_HOURS", 72)


class TimescaleHealthSnapshotRepository:
    """Read-only TimescaleDB queries for current HA sensor values."""

    async def _latest_quantity_value(self, session: AsyncSession, metric_name: str) -> object:
        return (
            await session.execute(
                text(
                    """
                    SELECT value
                    FROM quantity_samples
                    WHERE metric_name = :metric_name
                    ORDER BY time DESC
                    LIMIT 1
                    """
                ),
                {"metric_name": metric_name},
            )
        ).scalar_one_or_none()

    async def fetch_snapshot(self, session: AsyncSession) -> HealthSnapshot:
        collected_at = datetime.now(UTC)

        heart_rate = int_or_none(
            (
                await session.execute(
                    text(
                        """
                        SELECT bpm
                        FROM heart_rate
                        WHERE time > now() - make_interval(hours => :hrs)
                        ORDER BY time DESC
                        LIMIT 1
                        """
                    ),
                    {"hrs": _HR_FRESH_HOURS},
                )
            ).scalar_one_or_none()
        )
        resting_heart_rate_raw = await session.execute(
            text(
                """
                    SELECT bpm
                    FROM heart_rate
                    WHERE context = 'resting'
                    ORDER BY time DESC
                    LIMIT 1
                    """
            )
        )
        resting_heart_rate_value = resting_heart_rate_raw.scalar_one_or_none()
        if resting_heart_rate_value is None:
            resting_heart_rate_value = await self._latest_quantity_value(
                session, "resting_heart_rate"
            )
        resting_heart_rate = int_or_none(resting_heart_rate_value)
        hrv_7d_avg = round_float(
            (
                await session.execute(
                    text(
                        """
                        SELECT AVG(value_ms)
                        FROM hrv
                        WHERE time >= now() - interval '7 days'
                        """
                    )
                )
            ).scalar_one_or_none(),
            1,
        )
        hrv = round_float(
            (
                await session.execute(
                    text(
                        """
                        SELECT value_ms
                        FROM hrv
                        ORDER BY time DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none(),
            1,
        )
        steps_today = int_or_none(
            (
                await session.execute(
                    text(
                        """
                        SELECT steps
                        FROM daily_activity
                        WHERE date = current_date
                        ORDER BY date DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none()
        )
        active_calories = int_or_none(
            (
                await session.execute(
                    text(
                        """
                        SELECT active_calories
                        FROM daily_activity
                        WHERE active_calories IS NOT NULL
                        ORDER BY date DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none()
        )
        last_sleep_hours = round_float(
            (
                await session.execute(
                    text(
                        """
                        SELECT total_duration_ms / 3600000.0
                        FROM sleep_sessions
                        ORDER BY start_time DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none(),
            2,
        )
        sleep_efficiency_raw = await session.execute(
            text(
                """
                    SELECT CASE
                      WHEN (total_duration_ms + COALESCE(awake_ms, 0)) > 0
                      THEN total_duration_ms::float
                        / (total_duration_ms + COALESCE(awake_ms, 0)) * 100.0
                    END
                    FROM sleep_sessions
                    ORDER BY start_time DESC
                    LIMIT 1
                    """
            )
        )
        sleep_efficiency_value = sleep_efficiency_raw.scalar_one_or_none()
        if sleep_efficiency_value is None:
            sleep_efficiency_value = await self._latest_quantity_value(
                session, "sleep_efficiency_percentage"
            )
        sleep_efficiency = round_float(sleep_efficiency_value, 1)
        blood_oxygen = round_float(
            (
                await session.execute(
                    text(
                        """
                        SELECT spo2_pct
                        FROM blood_oxygen
                        ORDER BY time DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none(),
            1,
        )
        recovery_score_raw = await session.execute(
            text(
                """
                    SELECT score
                    FROM recovery
                    ORDER BY time DESC
                    LIMIT 1
                    """
            )
        )
        recovery_score_value = recovery_score_raw.scalar_one_or_none()
        if recovery_score_value is None:
            recovery_score_value = await self._latest_quantity_value(session, "recovery_score")
        recovery_score = int_or_none(recovery_score_value)
        strain = round_float(await self._latest_quantity_value(session, "strain"), 1)
        source_model = (
            await session.execute(
                text(
                    """
                    WITH recent_sources AS (
                        SELECT source_id, max(time) AS observed_at
                        FROM hrv
                        WHERE time >= now() - interval '7 days'
                        GROUP BY source_id
                        UNION ALL
                        SELECT source_id, max(time) AS observed_at
                        FROM blood_oxygen
                        WHERE time >= now() - interval '7 days'
                        GROUP BY source_id
                        UNION ALL
                        SELECT source_id, max(start_time) AS observed_at
                        FROM sleep_sessions
                        WHERE start_time >= now() - interval '7 days'
                        GROUP BY source_id
                        UNION ALL
                        SELECT source_id, max(date::timestamptz) AS observed_at
                        FROM daily_activity
                        WHERE date >= current_date - interval '7 days'
                        GROUP BY source_id
                    ),
                    ranked AS (
                        SELECT
                            CASE
                                WHEN lower(source_id) LIKE '%apple%watch%' THEN 'Apple Watch'
                                WHEN lower(source_id) LIKE '%whoop%' THEN 'WHOOP'
                                WHEN lower(source_id) LIKE '%zepp%'
                                  OR lower(source_id) LIKE '%amazfit%' THEN 'Amazfit / Zepp'
                                ELSE source_id
                            END AS label,
                            max(observed_at) AS observed_at
                        FROM recent_sources
                        WHERE source_id IS NOT NULL
                          AND btrim(source_id) <> ''
                        GROUP BY label
                        ORDER BY observed_at DESC
                        LIMIT 3
                    )
                    SELECT string_agg(label, ' + ' ORDER BY observed_at DESC)
                    FROM ranked
                    """
                )
            )
        ).scalar_one_or_none() or "HealthSave"
        latest_medication_status = (
            await session.execute(
                text(
                    """
                    SELECT status
                    FROM medication_dose_events
                    ORDER BY coalesce(scheduled_time, time) DESC, time DESC
                    LIMIT 1
                    """
                )
            )
        ).scalar_one_or_none()

        snapshot = HealthSnapshot(
            collected_at=collected_at,
            heart_rate=heart_rate,
            hrv_7d_avg=hrv_7d_avg,
            steps_today=steps_today,
            last_sleep_hours=last_sleep_hours,
            source_model=str(source_model),
            room_health_state=None,
            hrv=hrv,
            steps=steps_today,
            active_calories=active_calories,
            blood_oxygen=blood_oxygen,
            recovery_score=recovery_score,
            sleep_duration=last_sleep_hours,
            sleep_efficiency=sleep_efficiency,
            resting_heart_rate=resting_heart_rate,
            strain=strain,
            latest_medication_status=latest_medication_status,
        )
        return HealthSnapshot(
            collected_at=snapshot.collected_at,
            heart_rate=snapshot.heart_rate,
            hrv_7d_avg=snapshot.hrv_7d_avg,
            steps_today=snapshot.steps_today,
            last_sleep_hours=snapshot.last_sleep_hours,
            source_model=snapshot.source_model,
            room_health_state=derive_room_health_state(snapshot),
            hrv=snapshot.hrv,
            steps=snapshot.steps,
            active_calories=snapshot.active_calories,
            blood_oxygen=snapshot.blood_oxygen,
            recovery_score=snapshot.recovery_score,
            sleep_duration=snapshot.sleep_duration,
            sleep_efficiency=snapshot.sleep_efficiency,
            resting_heart_rate=snapshot.resting_heart_rate,
            strain=snapshot.strain,
            latest_medication_status=snapshot.latest_medication_status,
        )

    async def fetch_snapshots_by_source(self, session: AsyncSession) -> list[SourceHealthSnapshot]:
        """Per-``source_id`` latest values across all primary metrics.

        Migration 009 widened ``daily_activity`` and ``sleep_sessions``
        with ``source_id``; this method now queries all four sources of
        truth (heart_rate, hrv, daily_activity, sleep_sessions) and
        merges them per source.

        A snapshot is emitted for every ``source_id`` that has at
        least one recent row across any of the four metrics. Sources
        with no recent data do not appear — the bridge therefore only
        advertises HA sub-devices for actively-publishing sources, no
        stale ghost entities.

        Rows whose ``source_id`` is NULL or empty get bucketed under
        the slug ``"unknown"`` so a single sentinel sub-device collects
        legacy / uncategorized data instead of fragmenting it.
        """
        collected_at = datetime.now(UTC)

        # Latest heart_rate per source within 72h. Wider than the aggregate's
        # "latest sample" because a multi-device user doesn't sync every source
        # daily — a watch synced ~1-2 days ago is still a live source for the HA
        # "<source> available" sensors, not a ghost.
        hr_rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (source_id) source_id, bpm
                    FROM heart_rate
                    WHERE time > now() - make_interval(hours => :hrs)
                    ORDER BY source_id, time DESC
                    """
                ),
                {"hrs": _SOURCE_HR_FRESH_HOURS},
            )
        ).all()

        # Latest hrv per source within 7d.
        hrv_rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (source_id) source_id, value_ms
                    FROM hrv
                    WHERE time > now() - interval '7 days'
                    ORDER BY source_id, time DESC
                    """
                )
            )
        ).all()

        # Today's steps per source.
        steps_rows = (
            await session.execute(
                text(
                    """
                    SELECT source_id, steps
                    FROM daily_activity
                    WHERE date = current_date AND steps IS NOT NULL
                    """
                )
            )
        ).all()

        # Last sleep session per source (latest by start_time).
        sleep_rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (source_id) source_id, total_duration_ms
                    FROM sleep_sessions
                    WHERE total_duration_ms IS NOT NULL
                    ORDER BY source_id, start_time DESC
                    """
                )
            )
        ).all()

        # Merge by source_id. None/empty source_id collapses to one
        # 'unknown' bucket across all four passes.
        per_source: dict[str, dict[str, object]] = {}
        unknown_key = "_unknown_source_"

        for source_id, bpm in hr_rows:
            key = source_id if source_id else unknown_key
            per_source.setdefault(key, {"source_id": source_id or ""})
            per_source[key]["heart_rate"] = int_or_none(bpm)

        for source_id, value_ms in hrv_rows:
            key = source_id if source_id else unknown_key
            per_source.setdefault(key, {"source_id": source_id or ""})
            per_source[key]["hrv_latest_ms"] = round_float(value_ms, 1)

        for source_id, steps in steps_rows:
            key = source_id if source_id else unknown_key
            per_source.setdefault(key, {"source_id": source_id or ""})
            per_source[key]["steps_today"] = int_or_none(steps)

        for source_id, duration_ms in sleep_rows:
            key = source_id if source_id else unknown_key
            per_source.setdefault(key, {"source_id": source_id or ""})
            per_source[key]["last_sleep_hours"] = round_float(
                duration_ms / 3_600_000 if duration_ms is not None else None, 2
            )

        snapshots: list[SourceHealthSnapshot] = []
        for entry in per_source.values():
            snapshots.append(
                SourceHealthSnapshot(
                    collected_at=collected_at,
                    source_id=str(entry.get("source_id", "")),
                    heart_rate=entry.get("heart_rate"),  # type: ignore[arg-type]
                    hrv_latest_ms=entry.get("hrv_latest_ms"),  # type: ignore[arg-type]
                    steps_today=entry.get("steps_today"),  # type: ignore[arg-type]
                    last_sleep_hours=entry.get("last_sleep_hours"),  # type: ignore[arg-type]
                )
            )
        # Deterministic order so tests + log lines are stable.
        snapshots.sort(key=lambda s: s.slug)
        return snapshots
