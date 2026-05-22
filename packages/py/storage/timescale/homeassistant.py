"""Timescale read model for the Home Assistant MQTT bridge."""

from __future__ import annotations

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

    async def fetch_snapshots_by_source(self, session: AsyncSession) -> list[SourceHealthSnapshot]:
        """Per-``source_id`` latest values for source-tagged metrics.

        Returns one :class:`SourceHealthSnapshot` for every ``source_id``
        that has either a recent (<=24h) ``heart_rate`` row or a
        recent (<=7d) ``hrv`` row. Sources with no recent rows do not
        appear — the bridge therefore only advertises HA sub-devices
        for actively-publishing sources, no stale ghost entities.

        Rows whose ``source_id`` is NULL or empty get bucketed under
        the slug ``"unknown"`` so a single sentinel sub-device collects
        legacy / uncategorized data instead of fragmenting it.
        """
        collected_at = datetime.now(UTC)

        # Latest heart_rate per source within 24h. DISTINCT ON keeps
        # the most-recent row per source_id efficiently.
        hr_rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (source_id) source_id, bpm
                    FROM heart_rate
                    WHERE time > now() - interval '24 hours'
                    ORDER BY source_id, time DESC
                    """
                )
            )
        ).all()

        # Latest hrv per source within 7d (single most-recent value,
        # not the 7d average — the per-source view is "what is each
        # source reporting RIGHT NOW", not historical aggregate).
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

        # Merge by source_id. None/empty source_id is collapsed under
        # the same "_unknown_source_" key so the dedup is consistent
        # across the HR and HRV passes.
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

        snapshots: list[SourceHealthSnapshot] = []
        for entry in per_source.values():
            snapshots.append(
                SourceHealthSnapshot(
                    collected_at=collected_at,
                    source_id=str(entry.get("source_id", "")),
                    heart_rate=entry.get("heart_rate"),  # type: ignore[arg-type]
                    hrv_latest_ms=entry.get("hrv_latest_ms"),  # type: ignore[arg-type]
                )
            )
        # Deterministic order so tests + log lines are stable.
        snapshots.sort(key=lambda s: s.slug)
        return snapshots
