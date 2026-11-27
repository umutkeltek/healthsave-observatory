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

import asyncio
import logging
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig
from homeassistant_mqtt.client import PahoMQTTPublisher
from homeassistant_mqtt.config import load_config_from_env
from homeassistant_mqtt.liveness import BridgeStalled, LivenessWatchdog
from homeassistant_mqtt.main import (
    _run_loop,
    _warn_for_reserved_prefixes,
    build_session_messages,
    publish_once,
)
from homeassistant_mqtt.snapshot import (
    HealthSnapshot,
    MetricReadinessSnapshot,
    SourceHealthSnapshot,
)


@dataclass
class _RecordingPublisher:
    config: HomeAssistantMQTTConfig = field(default_factory=HomeAssistantMQTTConfig)
    published: list[tuple[str, Any, bool]] = field(default_factory=list)

    def publish_many(self, messages) -> bool:
        self.published.extend(messages)
        return True


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

    # Aggregate-device state goes out on the Observatory topic.
    assert "observatory/sensor/state" in topics

    # One per-source state topic per source snapshot.
    assert "observatory/source/apple_watch/state" in topics
    assert "observatory/source/whoop/state" in topics

    # Per-source discovery topics — at least one per populated metric.
    discovery_topics = [t for t in topics if t.startswith("homeassistant/sensor/observatory_")]
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
    assert publisher.published[0][0] == "observatory/sensor/state"
    per_source_topics = [m[0] for m in publisher.published if "/source/" in m[0]]
    assert per_source_topics == []
    discovery_topics = [
        m[0] for m in publisher.published if m[0].startswith("homeassistant/sensor/observatory_")
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
    assert "observatory/sensor/state" in topics
    assert "observatory/source/apple_watch/state" in topics
    assert "homeassistant/sensor/observatory_apple_watch/heart_rate/config" in topics

    assert "healthtrack/sensor/state" in topics
    assert "healthtrack/source/apple_watch/state" in topics
    assert "homeassistant/sensor/healthtrack_apple_watch/heart_rate/config" in topics

    legacy_state = next(
        payload for topic, payload, _ in publisher.published if topic == "healthtrack/sensor/state"
    )
    assert legacy_state["hrv"] == 58.0
    assert legacy_state["steps_today"] == 4200
    assert "steps" not in legacy_state
    assert legacy_state["sleep_duration"] == 7.25


@pytest.mark.asyncio
async def test_publish_once_readiness_entities_are_off_by_default_and_keep_state_fields():
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        heart_rate=None,
        hrv_7d_avg=None,
        steps_today=4200,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state=None,
        metric_readiness={
            "step_count": MetricReadinessSnapshot(
                metric="step_count",
                window_key="today_local",
                ready=True,
                status="ready",
            )
        },
    )
    repository = _StubRepository(aggregate=aggregate, per_source=[])
    publisher = _RecordingPublisher()

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher)

    topics = [topic for topic, _payload, _retain in publisher.published]
    assert not any("steps_today_ready/config" in topic for topic in topics)
    aggregate_state = next(
        payload
        for topic, payload, _retain in publisher.published
        if topic == "observatory/sensor/state"
    )
    assert aggregate_state["steps_today_ready"] is True
    assert aggregate_state["steps_today_status"] == "ready"


@pytest.mark.asyncio
async def test_publish_once_readiness_entities_can_be_enabled():
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        heart_rate=None,
        hrv_7d_avg=None,
        steps_today=4200,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state=None,
        metric_readiness={
            "step_count": MetricReadinessSnapshot(
                metric="step_count",
                window_key="today_local",
                ready=True,
                status="ready",
            )
        },
    )
    repository = _StubRepository(aggregate=aggregate, per_source=[])
    publisher = _RecordingPublisher()

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher, readiness_entities=True)

    topics = {topic for topic, _payload, _retain in publisher.published}
    assert "homeassistant/binary_sensor/observatory/steps_today_ready/config" in topics


@pytest.mark.asyncio
async def test_publish_once_filters_source_layer_with_slug_allowlist():
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=None,
        steps_today=None,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state=None,
    )
    per_source = [
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Apple Watch",
            heart_rate=72,
            hrv_latest_ms=None,
        ),
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Bug C Probe",
            heart_rate=99,
            hrv_latest_ms=None,
        ),
    ]
    repository = _StubRepository(aggregate=aggregate, per_source=per_source)
    publisher = _RecordingPublisher()

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(repository, publisher, source_slugs=frozenset({"apple_watch"}))

    topics = {topic for topic, _payload, _retain in publisher.published}
    assert "observatory/source/apple_watch/state" in topics
    assert "homeassistant/sensor/observatory_apple_watch/heart_rate/config" in topics
    assert "observatory/source/bug_c_probe/state" not in topics
    assert "homeassistant/sensor/observatory_bug_c_probe/heart_rate/config" not in topics


def _will_topic_of(monkeypatch, config: HomeAssistantMQTTConfig) -> str:
    """The topic the broker flips to "offline" when this config's connection dies."""

    fake_client = MagicMock()
    mqtt_mod = types.ModuleType("paho.mqtt.client")
    mqtt_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)  # type: ignore[attr-defined]
    mqtt_mod.Client = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", mqtt_mod)

    PahoMQTTPublisher(config).connect()
    fake_client.will_set.assert_called_once()
    return fake_client.will_set.call_args.args[0]


@pytest.mark.asyncio
async def test_every_discovered_entity_follows_the_connection_last_will(monkeypatch):
    """M19: MQTT allows one Last Will per connection, and a legacy alias
    publishes over the primary's connection. Legacy discovery used to name its
    own ``healthtrack/status`` topic, which nothing flips to "offline", so a dead
    bridge left every legacy entity showing its last value as live. Every
    discovery payload the bridge emits (primary or legacy; aggregate, readiness
    or per-source) must name the topic the will covers. Entity identity stays.
    """

    for var in (
        "HA_MQTT_STATE_TOPIC_PREFIX",
        "HA_MQTT_DEVICE_IDENTIFIER",
        "HA_MQTT_DEVICE_NAME",
        "HA_MQTT_DISCOVERY_PREFIX",
        "HA_MQTT_LEGACY_DEVICE_IDENTIFIER",
        "HA_MQTT_LEGACY_DEVICE_NAME",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HA_MQTT_LEGACY_STATE_TOPIC_PREFIX", "healthtrack")
    bridge_config = load_config_from_env()
    will_topic = _will_topic_of(monkeypatch, bridge_config.mqtt)

    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=None,
        steps_today=4200,
        last_sleep_hours=None,
        source_model="HealthSave",
        room_health_state=None,
        metric_readiness={
            "step_count": MetricReadinessSnapshot(
                metric="step_count", window_key="today_local", ready=True, status="ready"
            )
        },
    )
    per_source = [
        SourceHealthSnapshot(
            collected_at=aggregate.collected_at,
            source_id="Apple Watch",
            heart_rate=72,
            hrv_latest_ms=58.0,
        )
    ]
    publisher = _RecordingPublisher(config=bridge_config.mqtt)
    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await publish_once(
            _StubRepository(aggregate=aggregate, per_source=per_source),
            publisher,
            publish_configs=bridge_config.publish_configs,
            readiness_entities=True,
        )
    messages = build_session_messages(bridge_config.publish_configs) + publisher.published

    discovery = {topic: payload for topic, payload, _ in messages if topic.endswith("/config")}
    assert {
        "homeassistant/sensor/observatory/heart_rate/config",
        "homeassistant/sensor/healthtrack/heart_rate/config",
        "homeassistant/binary_sensor/healthtrack/steps_today_ready/config",
        "homeassistant/sensor/healthtrack_apple_watch/heart_rate/config",
    } <= discovery.keys()
    off_will = {
        topic: payload["availability_topic"]
        for topic, payload in discovery.items()
        if payload["availability_topic"] != will_topic
    }
    assert off_will == {}, f"entities not covered by the will on {will_topic}"

    # HA keys entities on unique_id and derives entity ids from object_id; both
    # are unchanged for the legacy alias, so existing users keep their entities.
    legacy_hr = discovery["homeassistant/sensor/healthtrack/heart_rate/config"]
    assert legacy_hr["unique_id"] == "healthtrack_heart_rate"
    assert legacy_hr["object_id"] == "heart_rate"
    assert legacy_hr["state_topic"] == "healthtrack/sensor/state"


def test_reserved_healthsave_prefix_logs_ios_app_collision_warning(caplog):
    configs = (
        HomeAssistantMQTTConfig(),
        HomeAssistantMQTTConfig(
            state_topic_prefix="/HealthSave/",
            device_identifier="legacy-healthsave",
            device_name="Legacy HealthSave",
        ),
    )

    with caplog.at_level(logging.WARNING, logger="healthsave.homeassistant_mqtt"):
        _warn_for_reserved_prefixes(configs)

    assert "sensor.healthsave_*" in caplog.text
    assert "iOS app" in caplog.text
    assert "reserved" in caplog.text


# --- Liveness watchdog + run-loop self-heal ----------------------------------
#
# The bridge once went silently dark for ~8 days: the loop kept spinning but
# every publish was skipped, so nothing raised and the container never
# restarted. These tests pin the fix — a sustained no-publish MUST escalate
# (raise BridgeStalled), and a healthy loop MUST update the heartbeat and stop
# cleanly. Without the watchdog the dark-loop test loops forever; the
# asyncio.wait_for guard turns that hang into a clear failure.


def test_liveness_watchdog_flags_stall_after_deadline():
    wd = LivenessWatchdog(deadline_seconds=10)
    # Not armed yet -> never stalled (no false positive before mark_start).
    assert wd.is_stalled(now=1000.0) is False
    wd.mark_start(now=100.0)
    assert wd.is_stalled(now=109.9) is False  # within deadline
    assert wd.is_stalled(now=110.1) is True  # just past deadline
    # A successful publish resets the clock.
    wd.record_publish(now=200.0)
    assert wd.is_stalled(now=209.0) is False
    assert wd.is_stalled(now=211.0) is True
    assert wd.seconds_since_publish(now=205.0) == pytest.approx(5.0)


@dataclass
class _LoopPublisher:
    """Publisher double for the run loop. ``connected=False`` simulates a broker
    outage / dead paho thread: every publish_many is skipped (returns False)."""

    connected: bool = True
    config: HomeAssistantMQTTConfig = field(default_factory=HomeAssistantMQTTConfig)
    calls: int = 0
    stop_event: asyncio.Event | None = None
    stop_after_calls: int = 0

    def publish_many(self, messages) -> bool:
        self.calls += 1
        if (
            self.stop_event is not None
            and self.stop_after_calls
            and self.calls >= self.stop_after_calls
        ):
            self.stop_event.set()
        return self.connected


def _live_snapshot_repository() -> _StubRepository:
    aggregate = HealthSnapshot(
        collected_at=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
        heart_rate=72,
        hrv_7d_avg=58.0,
        steps_today=4200,
        last_sleep_hours=7.25,
        source_model="HealthSave",
        room_health_state="normal",
    )
    return _StubRepository(aggregate=aggregate, per_source=[])


@pytest.mark.asyncio
async def test_run_loop_exits_when_publishing_stays_dark(tmp_path):
    """A sustained silent outage must raise BridgeStalled (self-heal), not hang."""

    stop_event = asyncio.Event()
    publisher = _LoopPublisher(connected=False)  # every publish is skipped
    repository = _live_snapshot_repository()
    watchdog = LivenessWatchdog(deadline_seconds=0.05)
    loop = asyncio.get_running_loop()

    async def drive():
        with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
            await _run_loop(
                repository=repository,
                publisher=publisher,
                publish_configs=(publisher.config,),
                stop_event=stop_event,
                watchdog=watchdog,
                heartbeat_path=str(tmp_path / "heartbeat"),
                publish_interval_seconds=0,  # spin fast so the deadline is reached
                now=loop.time,
            )

    # The guard turns a regression (no escalation -> infinite loop) into a clear
    # timeout failure instead of a hung test run.
    with pytest.raises(BridgeStalled):
        await asyncio.wait_for(drive(), timeout=5.0)


@pytest.mark.asyncio
async def test_run_loop_healthy_updates_heartbeat_and_stops_cleanly(tmp_path):
    """A connected loop updates the heartbeat and exits cleanly on stop (no stall)."""

    stop_event = asyncio.Event()
    heartbeat = tmp_path / "heartbeat"
    # Stop as soon as the first publish goes out so the loop ends deterministically.
    publisher = _LoopPublisher(connected=True, stop_event=stop_event, stop_after_calls=1)
    repository = _live_snapshot_repository()
    watchdog = LivenessWatchdog(deadline_seconds=100)
    loop = asyncio.get_running_loop()

    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await asyncio.wait_for(
            _run_loop(
                repository=repository,
                publisher=publisher,
                publish_configs=(publisher.config,),
                stop_event=stop_event,
                watchdog=watchdog,
                heartbeat_path=str(heartbeat),
                publish_interval_seconds=0,
                now=loop.time,
            ),
            timeout=5.0,
        )

    # Heartbeat written with a real float timestamp; loop exited without stalling.
    assert heartbeat.exists()
    float(heartbeat.read_text())


# --- Aged-out sources (M19) ---------------------------------------------------
#
# A source that drops out of fetch_snapshots_by_source (no recent row in any of
# its windows) used to keep its retained discovery AND retained state on the
# broker forever, so Home Assistant showed a frozen sensor as current. These
# tests pin the fix: per-source entities expire in HA once the bridge stops
# refreshing them, the bridge clears the retained state of a source it saw age
# out, and it never deletes the entities themselves.


class _AgingRepository:
    """Serves one per-source list per cycle; stops the loop after the last one."""

    def __init__(
        self,
        cycles: list[list[SourceHealthSnapshot] | Exception],
        publisher: _RecordingPublisher,
        stop_event: asyncio.Event,
    ) -> None:
        self._cycles = cycles
        self._publisher = publisher
        self._stop_event = stop_event
        # Index into publisher.published where each cycle's messages begin.
        self.cycle_starts: list[int] = []

    async def fetch_snapshot(self, _session) -> HealthSnapshot:
        return _live_snapshot_repository()._aggregate

    async def fetch_snapshots_by_source(self, _session) -> list[SourceHealthSnapshot]:
        self.cycle_starts.append(len(self._publisher.published))
        cycle = self._cycles[len(self.cycle_starts) - 1]
        if len(self.cycle_starts) == len(self._cycles):
            self._stop_event.set()
        if isinstance(cycle, Exception):
            raise cycle
        return cycle


def _source(source_id: str, **values: Any) -> SourceHealthSnapshot:
    return SourceHealthSnapshot(
        collected_at=datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
        source_id=source_id,
        heart_rate=values.get("heart_rate"),
        hrv_latest_ms=values.get("hrv_latest_ms"),
        steps_today=values.get("steps_today"),
        last_sleep_hours=values.get("last_sleep_hours"),
    )


async def _drive_cycles(tmp_path, cycles) -> tuple[_RecordingPublisher, list[int]]:
    stop_event = asyncio.Event()
    publisher = _RecordingPublisher()
    repository = _AgingRepository(cycles, publisher, stop_event)
    loop = asyncio.get_running_loop()
    with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
        await asyncio.wait_for(
            _run_loop(
                repository=repository,
                publisher=publisher,
                publish_configs=(publisher.config,),
                stop_event=stop_event,
                watchdog=LivenessWatchdog(deadline_seconds=100),
                heartbeat_path=str(tmp_path / "heartbeat"),
                publish_interval_seconds=0,
                now=loop.time,
            ),
            timeout=5.0,
        )
    return publisher, repository.cycle_starts


@pytest.mark.asyncio
async def test_aged_out_source_expires_in_ha_and_loses_its_retained_state(tmp_path):
    watch = _source("Apple Watch", heart_rate=72, hrv_latest_ms=58.0)
    iphone = _source("iPhone", steps_today=4200)
    publisher, starts = await _drive_cycles(tmp_path, [[watch, iphone], [watch]])
    first, second = publisher.published[: starts[1]], publisher.published[starts[1] :]

    # Every per-source entity tells HA to expire it once the bridge stops
    # refreshing its state topic: the bridge republishes each live source every
    # cycle, so only a source that aged out of the snapshot (or a dead bridge)
    # goes quiet that long. Several skipped cycles must not flap it.
    interval = publisher.config.publish_interval_seconds
    source_discovery = [
        payload
        for topic, payload, _ in first
        if topic.startswith("homeassistant/sensor/observatory_")
    ]
    assert source_discovery
    for payload in source_discovery:
        assert payload.get("expire_after", 0) >= 3 * interval, payload["unique_id"]

    # The iPhone aged out: its retained state is cleared (an empty retained
    # payload deletes it on the broker) so an HA restart cannot replay it as
    # current. Its discovery is left alone: the entities stay, unavailable.
    assert ("observatory/source/iphone/state", "", True) in second
    assert not [t for t, _, _ in second if t.startswith("homeassistant/sensor/observatory_iphone")]
    # The still-live watch is untouched by the cleanup.
    assert ("observatory/source/apple_watch/state", "", True) not in second
    assert "observatory/source/apple_watch/state" in [t for t, _, _ in second]


@pytest.mark.asyncio
async def test_failed_source_fetch_is_not_mistaken_for_every_source_aging_out(tmp_path):
    watch = _source("Apple Watch", heart_rate=72)
    publisher, starts = await _drive_cycles(
        tmp_path, [[watch], RuntimeError("db stalled"), [watch]]
    )

    cleared = [topic for topic, payload, _ in publisher.published if payload == ""]
    assert cleared == []


@pytest.mark.asyncio
async def test_clearing_an_aged_out_source_retries_after_an_outage():
    watch = _source("Apple Watch", heart_rate=72)
    retained: set[str] = set()
    aggregate = _live_snapshot_repository()._aggregate

    async def cycle(per_source, publisher):
        with patch("homeassistant_mqtt.main.async_session", _FakeAsyncSessionFactory()):
            await publish_once(
                _StubRepository(aggregate=aggregate, per_source=per_source),
                publisher,
                retained_source_topics=retained,
            )

    await cycle([watch], _RecordingPublisher())
    assert retained == {"observatory/source/apple_watch/state"}

    # The watch ages out while the broker is unreachable: nothing went out, so
    # the bridge must still remember the topic it has to clear.
    await cycle([], _LoopPublisher(connected=False))
    assert retained == {"observatory/source/apple_watch/state"}

    reconnected = _RecordingPublisher()
    await cycle([], reconnected)
    assert ("observatory/source/apple_watch/state", "", True) in reconnected.published
    assert retained == set()
