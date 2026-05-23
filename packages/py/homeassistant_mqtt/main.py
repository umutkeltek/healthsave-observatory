"""Long-running Home Assistant MQTT bridge entrypoint."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from server.db.session import async_session, engine
from storage.timescale.homeassistant import TimescaleHealthSnapshotRepository

from .bridge import (
    HomeAssistantMQTTConfig,
    build_availability_message,
    build_discovery_messages,
    build_legacy_availability_messages,
    build_source_discovery_messages,
    build_source_state_message,
    build_state_messages,
    sensor_specs_for_config,
)
from .client import PahoMQTTPublisher
from .config import load_config_from_env

log = logging.getLogger("healthsave.homeassistant_mqtt")


async def publish_once(
    repository: TimescaleHealthSnapshotRepository,
    publisher: PahoMQTTPublisher,
    publish_configs: tuple[HomeAssistantMQTTConfig, ...] | None = None,
) -> None:
    """Fetch one aggregate + per-source snapshot pass and publish them.

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

    for config in configs:
        specs = sensor_specs_for_config(config)

        # Aggregate parent device — unchanged behaviour for backward-compat.
        publisher.publish_many(build_state_messages(config, specs, snapshot))

        # Per-source sub-devices.
        for source in source_snapshots:
            publisher.publish_many(build_source_discovery_messages(config, source))
            publisher.publish_many([build_source_state_message(config, source)])


async def run() -> None:
    bridge_config = load_config_from_env()
    if not bridge_config.enabled:
        log.info("Home Assistant MQTT bridge disabled; set HA_MQTT_ENABLED=true to run")
        return

    repository = TimescaleHealthSnapshotRepository()
    publisher = PahoMQTTPublisher(bridge_config.mqtt)
    publisher.connect()
    publish_configs = bridge_config.publish_configs
    for config in publish_configs:
        specs = sensor_specs_for_config(config)
        publisher.publish_many(
            [build_availability_message(config)] + build_legacy_availability_messages(config)
        )
        publisher.publish_many(build_discovery_messages(config, specs))
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

    try:
        while not stop_event.is_set():
            try:
                await publish_once(repository, publisher, publish_configs=publish_configs)
            except Exception:
                log.exception("Home Assistant MQTT bridge publish failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=bridge_config.mqtt.publish_interval_seconds,
                )
    finally:
        publisher.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
