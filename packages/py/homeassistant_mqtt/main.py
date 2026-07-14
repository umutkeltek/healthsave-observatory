"""Long-running Home Assistant MQTT bridge entrypoint."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Callable
from contextlib import suppress

from server.db.session import async_session, engine
from storage.timescale.homeassistant import TimescaleHealthSnapshotRepository

from .bridge import (
    HomeAssistantMQTTConfig,
    MQTTMessage,
    build_availability_message,
    build_discovery_messages,
    build_legacy_availability_messages,
    build_readiness_discovery_messages,
    build_source_discovery_messages,
    build_source_state_message,
    build_state_messages,
    sensor_specs_for_config,
)
from .client import PahoMQTTPublisher
from .config import load_config_from_env
from .liveness import BridgeStalled, LivenessWatchdog

log = logging.getLogger("healthsave.homeassistant_mqtt")


def _write_heartbeat(path: str) -> None:
    """Touch the heartbeat file so a Docker HEALTHCHECK can read its freshness.

    Best-effort: a filesystem hiccup must not take the bridge down (the liveness
    watchdog is the authoritative self-heal; the heartbeat is the observability
    signal).
    """

    try:
        with open(path, "w") as fh:
            fh.write(str(time.time()))
    except OSError:
        log.warning("could not write MQTT heartbeat file %s", path, exc_info=True)


async def publish_once(
    repository: TimescaleHealthSnapshotRepository,
    publisher: PahoMQTTPublisher,
    publish_configs: tuple[HomeAssistantMQTTConfig, ...] | None = None,
) -> bool:
    """Fetch one aggregate + per-source snapshot pass and publish them.

    Returns ``True`` if at least one publish actually went out this cycle (i.e.
    the client was connected), ``False`` if every publish was skipped because the
    broker was unreachable. The caller's liveness watchdog uses this to tell a
    healthy cycle from a silent outage.

    P5-d: in addition to the aggregate-device state on
    ``<prefix>/sensor/state``, we now also publish one retained-state
    payload per active source on ``<prefix>/source/<slug>/state``.
    Discovery messages for each source go out the same cycle so HA
    picks up newly-appeared sources without needing a separate startup
    event — retained means HA only re-processes when payload changes.
    """

    configs = publish_configs or (publisher.config,)
    async with async_session() as session:
        snapshot = await repository.fetch_snapshot(session)
        source_snapshots = await repository.fetch_snapshots_by_source(session)

    published = False
    for config in configs:
        specs = sensor_specs_for_config(config)

        # Aggregate parent device — unchanged behaviour for backward-compat.
        published |= publisher.publish_many(build_readiness_discovery_messages(config, snapshot))
        published |= publisher.publish_many(build_state_messages(config, specs, snapshot))

        # Per-source sub-devices.
        for source in source_snapshots:
            published |= publisher.publish_many(build_source_discovery_messages(config, source))
            published |= publisher.publish_many([build_source_state_message(config, source)])

    return published


async def _run_loop(
    *,
    repository: TimescaleHealthSnapshotRepository,
    publisher: PahoMQTTPublisher,
    publish_configs: tuple[HomeAssistantMQTTConfig, ...],
    stop_event: asyncio.Event,
    watchdog: LivenessWatchdog,
    heartbeat_path: str,
    publish_interval_seconds: int,
    now: Callable[[], float],
) -> None:
    """Drive the periodic publish cycle with liveness + heartbeat.

    Extracted from ``run`` so the escalation path is unit-testable without real
    signals, sockets, or a DB engine. Raises :class:`BridgeStalled` when no
    publish has actually gone out within the watchdog deadline, so the process
    exits non-zero and Docker restarts a clean one.
    """

    # Bound each publish cycle so a stalled DB await (or any hang inside
    # publish_once) cannot freeze the loop — a timed-out cycle is logged and the
    # next retries; paho keeps the MQTT socket alive on its own thread throughout.
    publish_cycle_timeout_s = max(5, min(publish_interval_seconds, 30))

    watchdog.mark_start(now())
    _write_heartbeat(heartbeat_path)

    while not stop_event.is_set():
        published = False
        try:
            published = await asyncio.wait_for(
                publish_once(repository, publisher, publish_configs=publish_configs),
                timeout=publish_cycle_timeout_s,
            )
        except TimeoutError:
            log.warning(
                "Home Assistant MQTT bridge publish cycle timed out after %ss; retrying next cycle",
                publish_cycle_timeout_s,
            )
        except Exception:
            log.exception("Home Assistant MQTT bridge publish failed")

        if published:
            watchdog.record_publish(now())
            _write_heartbeat(heartbeat_path)
        elif watchdog.is_stalled(now()):
            # Sustained silent-dark: the loop is alive but nothing is reaching the
            # broker (paho thread dead / permanent disconnect / DB always stalling).
            # Exit loudly so Docker (restart: unless-stopped) revives a clean
            # process with a fresh paho thread + DB engine.
            log.error(
                "Home Assistant MQTT bridge has not published for %.0fs "
                "(deadline %ss); exiting for a clean restart",
                watchdog.seconds_since_publish(now()),
                watchdog.deadline_seconds,
            )
            raise BridgeStalled(
                "HA MQTT bridge stalled: no successful publish within the liveness deadline"
            )

        with suppress(TimeoutError):
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=publish_interval_seconds,
            )


async def run() -> None:
    bridge_config = load_config_from_env()
    if not bridge_config.enabled:
        log.info("Home Assistant MQTT bridge disabled; set HA_MQTT_ENABLED=true to run")
        return

    repository = TimescaleHealthSnapshotRepository()
    publish_configs = bridge_config.publish_configs

    def session_messages() -> list[MQTTMessage]:
        """Availability(online) + discovery to (re)assert on every connect.

        Pure (config-only), so it is safe to call from paho's network thread in
        the on_connect callback. State messages are intentionally *not* here:
        they need a DB snapshot and flow on the periodic ``publish_once`` cycle
        (and stay retained on the broker across reconnects).
        """

        messages: list[MQTTMessage] = []
        for config in publish_configs:
            specs = sensor_specs_for_config(config)
            messages.append(build_availability_message(config))
            messages.extend(build_legacy_availability_messages(config))
            messages.extend(build_discovery_messages(config, specs))
        return messages

    publisher = PahoMQTTPublisher(bridge_config.mqtt, on_connect_messages=session_messages)
    publisher.connect()
    if not publisher.wait_until_connected(timeout=10.0):
        log.warning(
            "MQTT broker %s:%s not reachable yet; bridge will keep retrying in the background",
            bridge_config.mqtt.broker,
            bridge_config.mqtt.port,
        )
    log.info(
        "Home Assistant MQTT bridge publishing to broker=%s port=%s prefixes=%s",
        bridge_config.mqtt.broker,
        bridge_config.mqtt.port,
        ",".join(config.state_topic_prefix for config in publish_configs),
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    watchdog = LivenessWatchdog(bridge_config.liveness_deadline_seconds)
    try:
        await _run_loop(
            repository=repository,
            publisher=publisher,
            publish_configs=publish_configs,
            stop_event=stop_event,
            watchdog=watchdog,
            heartbeat_path=bridge_config.heartbeat_path,
            publish_interval_seconds=bridge_config.mqtt.publish_interval_seconds,
            now=loop.time,
        )
    finally:
        publisher.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(run())
    except BridgeStalled:
        # Non-zero exit so the container restart policy (unless-stopped) revives
        # the bridge with a clean process instead of leaving it silently dark.
        log.error("Home Assistant MQTT bridge exiting (code 1) after a liveness stall")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
