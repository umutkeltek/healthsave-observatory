"""Orchestration test for ``homeassistant_mqtt.main.publish_once``.

P5-d wires per-source publishing alongside the legacy aggregate
publish. The function now reads two snapshots from the repository and
emits two layers of messages. This test pins the orchestration with
recording doubles — no DB, no MQTT.

Intentionally not testing ``main.run()`` directly: it owns the
asyncio event loop + signal handlers + MQTT connect/close lifecycle,
which is integration territory. ``publish_once`` is the contract
that matters for shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig
from homeassistant_mqtt.main import publish_once
from homeassistant_mqtt.snapshot import HealthSnapshot, SourceHealthSnapshot


@dataclass
class _RecordingPublisher:
    config: HomeAssistantMQTTConfig = field(default_factory=HomeAssistantMQTTConfig)
    published: list[tuple[str, Any, bool]] = field(default_factory=list)

    def publish_many(self, messages):
        self.published.extend(messages)


class _StubRepository:
    """Stand-in for TimescaleHealthSnapshotRepository."""

    def __init__(
        self,
        *,
        aggregate: HealthSnapshot,
        per_source: list[SourceHealthSnapshot],
    ) -> None:
        self._aggregate = aggregate
        self._per_source = per_source
        self.fetch_aggregate_calls = 0
        self.fetch_per_source_calls = 0

    async def fetch_snapshot(self, _session) -> HealthSnapshot:
        self.fetch_aggregate_calls += 1
        return self._aggregate

    async def fetch_snapshots_by_source(self, _session) -> list[SourceHealthSnapshot]:
        self.fetch_per_source_calls += 1
        return self._per_source


class _FakeAsyncSessionFactory:
    """Async context manager returning a placeholder session object."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_publish_once_emits_aggregate_plus_per_source_layers():
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=58.0,
        steps_today=4200,
        last_sleep_hours=7.25,
        source_model="Apple Watch via HealthSave",
        room_health_state="normal",
    )
    per_source = [
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Apple Watch",
            heart_rate=72,
            hrv_latest_ms=64.3,
            steps_today=4200,
            last_sleep_hours=7.25,
        ),
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Whoop",
            heart_rate=68,
            hrv_latest_ms=58.5,
            steps_today=None,
            last_sleep_hours=7.0,
        ),
    ]
    repository = _StubRepository(aggregate=aggregate, per_source=per_source)
    publisher = _RecordingPublisher()

    # Patch the session factory used by main.publish_once.
    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher)

    # Both repo methods were called exactly once.
    assert repository.fetch_aggregate_calls == 1
    assert repository.fetch_per_source_calls == 1

    topics = [m[0] for m in publisher.published]

    # Aggregate-device state goes out on the legacy topic.
    assert "healthsave/sensor/state" in topics

    # One per-source state topic per source snapshot.
    assert "healthsave/source/apple_watch/state" in topics
    assert "healthsave/source/whoop/state" in topics

    # Per-source discovery topics — at least one per populated metric.
    discovery_topics = [t for t in topics if t.startswith("homeassistant/sensor/healthsave_")]
    # Apple Watch has all four metrics; Whoop has three (no steps).
    assert len(discovery_topics) == 4 + 3


@pytest.mark.asyncio
async def test_publish_once_is_a_noop_for_per_source_when_no_sources_active():
    """No active source data -> only the aggregate state message goes
    out. No discovery storm for an empty source list.
    """
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        heart_rate=None,
        hrv_7d_avg=None,
        steps_today=None,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state="normal",
    )
    repository = _StubRepository(aggregate=aggregate, per_source=[])
    publisher = _RecordingPublisher()

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher)

    # One aggregate state message; no per-source messages at all.
    assert publisher.published[0][0] == "healthsave/sensor/state"
    per_source_topics = [m[0] for m in publisher.published if "/source/" in m[0]]
    assert per_source_topics == []
    discovery_topics = [
        m[0] for m in publisher.published if m[0].startswith("homeassistant/sensor/healthsave_")
    ]
    assert discovery_topics == []


@pytest.mark.asyncio
async def test_publish_once_emits_primary_and_legacy_alias_shapes():
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=58.0,
        steps_today=4200,
        last_sleep_hours=7.25,
        source_model="Apple Watch via HealthSave",
        room_health_state="normal",
        hrv=58.0,
        steps=4200,
        sleep_duration=7.25,
    )
    per_source = [
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Apple Watch",
            heart_rate=72,
            hrv_latest_ms=58.0,
            steps_today=4200,
            last_sleep_hours=7.25,
        ),
    ]
    repository = _StubRepository(aggregate=aggregate, per_source=per_source)
    publisher = _RecordingPublisher()
    legacy = HomeAssistantMQTTConfig(
        state_topic_prefix="healthtrack",
        device_identifier="healthtrack",
        device_name="HealthTrack",
    )

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher, publish_configs=(publisher.config, legacy))

    topics = [m[0] for m in publisher.published]
    assert "healthsave/sensor/state" in topics
    assert "healthsave/source/apple_watch/state" in topics
    assert "homeassistant/sensor/healthsave_apple_watch/heart_rate/config" in topics

    assert "healthtrack/sensor/state" in topics
    assert "healthtrack/source/apple_watch/state" in topics
    assert "homeassistant/sensor/healthtrack_apple_watch/heart_rate/config" in topics

    legacy_state = next(
        payload for topic, payload, _ in publisher.published if topic == "healthtrack/sensor/state"
    )
    assert legacy_state["hrv"] == 58.0
    assert legacy_state["steps"] == 4200
    assert legacy_state["sleep_duration"] == 7.25
