"""Timescale read model for the Home Assistant MQTT bridge."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from homeassistant_mqtt.snapshot import (
    HealthSnapshot,
    derive_room_health_state,
    int_or_none,
    round_float,
)


class TimescaleHealthSnapshotRepository:
    """Read-only TimescaleDB queries for current HA sensor values."""

    async def fetch_snapshot(self, session: AsyncSession) -> HealthSnapshot:
        collected_at = datetime.now(UTC)

        heart_rate = int_or_none(
            (
                await session.execute(
                    text(
                        """
                        SELECT bpm
                        FROM heart_rate
                        WHERE time > now() - interval '24 hours'
                        ORDER BY time DESC
                        LIMIT 1
                        """
                    )
                )
            ).scalar_one_or_none()
        )
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
        source_model = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(d.device_model, d.device_type, 'HealthSave')
                    FROM devices d
                    ORDER BY d.registered_at DESC
                    LIMIT 1
                    """
                )
            )
        ).scalar_one_or_none() or "HealthSave"

        snapshot = HealthSnapshot(
            collected_at=collected_at,
            heart_rate=heart_rate,
            hrv_7d_avg=hrv_7d_avg,
            steps_today=steps_today,
            last_sleep_hours=last_sleep_hours,
            source_model=str(source_model),
            room_health_state=None,
        )
        return HealthSnapshot(
            collected_at=snapshot.collected_at,
            heart_rate=snapshot.heart_rate,
            hrv_7d_avg=snapshot.hrv_7d_avg,
            steps_today=snapshot.steps_today,
            last_sleep_hours=snapshot.last_sleep_hours,
            source_model=snapshot.source_model,
            room_health_state=derive_room_health_state(snapshot),
        )
