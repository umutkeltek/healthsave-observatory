"""Long-running Home Assistant MQTT bridge entrypoint."""

from __future__ import annotations

import asyncio
import logging
import signal

from server.db.session import async_session, engine

from storage.timescale.homeassistant import TimescaleHealthSnapshotRepository

from .bridge import (
    build_availability_message,
    build_discovery_messages,
    build_state_messages,
    default_sensor_specs,
)
from .client import PahoMQTTPublisher
from .config import load_config_from_env

log = logging.getLogger("healthsave.homeassistant_mqtt")


async def publish_once(
    repository: TimescaleHealthSnapshotRepository, publisher: PahoMQTTPublisher
) -> None:
    """Fetch one DB snapshot and publish retained HA state messages."""

    specs = default_sensor_specs()
    async with async_session() as session:
        snapshot = await repository.fetch_snapshot(session)
    publisher.publish_many(build_state_messages(publisher.config, specs, snapshot))


async def run() -> None:
    bridge_config = load_config_from_env()
    if not bridge_config.enabled:
        log.info("Home Assistant MQTT bridge disabled; set HA_MQTT_ENABLED=true to run")
        return

    repository = TimescaleHealthSnapshotRepository()
    publisher = PahoMQTTPublisher(bridge_config.mqtt)
    publisher.connect()
    specs = default_sensor_specs()
    publisher.publish_many([build_availability_message(bridge_config.mqtt)])
    publisher.publish_many(build_discovery_messages(bridge_config.mqtt, specs))
    log.info(
        "Home Assistant MQTT bridge publishing %s sensors to broker=%s port=%s prefix=%s",
        len(specs),
        bridge_config.mqtt.broker,
        bridge_config.mqtt.port,
        bridge_config.mqtt.state_topic_prefix,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        while not stop_event.is_set():
            try:
                await publish_once(repository, publisher)
            except Exception:
                log.exception("Home Assistant MQTT bridge publish failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=bridge_config.mqtt.publish_interval_seconds,
                )
            except TimeoutError:
                pass
    finally:
        publisher.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
