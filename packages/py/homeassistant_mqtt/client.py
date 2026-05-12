"""MQTT client wrapper for retained JSON Home Assistant messages."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .bridge import HomeAssistantMQTTConfig, MQTTMessage


class PahoMQTTPublisher:
    """Tiny wrapper around paho-mqtt so the bridge core stays testable."""

    def __init__(self, config: HomeAssistantMQTTConfig) -> None:
        self.config = config
        self._client: Any | None = None

    def connect(self) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.config.username:
            client.username_pw_set(self.config.username, self.config.password or None)
        client.connect(self.config.broker, self.config.port, keepalive=60)
        client.loop_start()
        self._client = client

    def publish_many(self, messages: Iterable[MQTTMessage]) -> None:
        if self._client is None:
            raise RuntimeError("MQTT publisher is not connected")
        for topic, payload, retain in messages:
            body = (
                payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
            )
            info = self._client.publish(topic, body, qos=0, retain=retain)
            info.wait_for_publish()

    def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
