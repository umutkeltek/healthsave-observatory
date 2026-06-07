"""Resilient MQTT client wrapper for retained Home Assistant messages.

The bridge must survive any broker blip, network change, or start-order
without silently going dark. The resilience contract lives here:

- ``connect_async`` + ``loop_start`` — the bridge can start *before* the broker
  is up and keeps retrying in the background (start-order independent).
- ``reconnect_delay_set`` — automatic bounded-backoff reconnection after any
  dropped connection.
- ``on_connect`` re-asserts availability ``online`` + discovery on **every**
  (re)connection. This is the critical fix: on a drop the broker publishes the
  retained LWT ``offline``, so without re-asserting ``online`` Home Assistant
  stays ``unavailable`` even once the socket recovers and state resumes.
- ``on_disconnect`` logs the drop (it used to be invisible).
- ``publish_many`` skips a cycle gracefully while disconnected instead of
  raising on every publish during an outage.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

from .bridge import HomeAssistantMQTTConfig, MQTTMessage, availability_topic

log = logging.getLogger("healthsave.homeassistant_mqtt")

# QoS 0 is sufficient for resilience here: every message is retained, the bridge
# re-publishes on a fixed interval, and availability + discovery are re-asserted
# on every (re)connect — so a packet dropped during a blip is superseded within
# one cycle without queue-growth risk during a long outage.
_QOS = 0
# Bound paho's auto-reconnect backoff: retry a flapping broker promptly, but
# don't hammer a broker that's down for a while.
_RECONNECT_MIN_DELAY = 1
_RECONNECT_MAX_DELAY = 120

# Returns availability(online) + discovery messages to (re)assert on connect.
SessionMessages = Callable[[], Iterable[MQTTMessage]]


class PahoMQTTPublisher:
    """Tiny, resilient wrapper around paho-mqtt so the bridge core stays testable."""

    def __init__(
        self,
        config: HomeAssistantMQTTConfig,
        *,
        on_connect_messages: SessionMessages | None = None,
    ) -> None:
        self.config = config
        self._on_connect_messages = on_connect_messages
        self._client: Any | None = None
        self._connected = threading.Event()

    def connect(self) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.config.username:
            client.username_pw_set(self.config.username, self.config.password or None)
        # Last Will & Testament: if the bridge crashes or the network drops, the
        # broker auto-publishes "offline" (retained) to the availability topic so
        # Home Assistant marks every HealthSave entity unavailable instead of
        # leaving the last retained value showing as if it were live.
        client.will_set(availability_topic(self.config), payload="offline", qos=_QOS, retain=True)
        # Automatic, bounded-backoff reconnection after any dropped connection.
        client.reconnect_delay_set(min_delay=_RECONNECT_MIN_DELAY, max_delay=_RECONNECT_MAX_DELAY)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        # connect_async (not connect) so a broker that isn't up yet at boot does
        # not crash the bridge — loop_start keeps retrying until it appears.
        client.connect_async(self.config.broker, self.config.port, keepalive=60)
        client.loop_start()
        self._client = client

    def wait_until_connected(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds for the first successful connect."""

        return self._connected.wait(timeout=timeout)

    def _on_connect(
        self, client: Any, _userdata: Any, _flags: Any, reason_code: Any, *_: Any
    ) -> None:
        is_failure = getattr(reason_code, "is_failure", None)
        if is_failure is None:  # int reason code: 0 == success
            is_failure = bool(reason_code)
        if is_failure:
            log.warning("MQTT connect refused by broker (reason=%s)", reason_code)
            return
        log.info("MQTT connected to %s:%s", self.config.broker, self.config.port)
        # Re-assert availability "online" + discovery on every (re)connect. The
        # retained LWT "offline" is still on the broker after a drop, so this is
        # what brings HA back from "unavailable" once the socket recovers.
        if self._on_connect_messages is not None:
            try:
                self._publish_each(client, self._on_connect_messages())
            except Exception:
                log.exception("MQTT on-connect re-assert failed")
        # Set last, so a publish_many returning during reconnect only proceeds
        # once availability + discovery have already gone out.
        self._connected.set()

    def _on_disconnect(self, _client: Any, _userdata: Any, *args: Any) -> None:
        # paho's on_disconnect signature varies across callback API versions
        # (VERSION2: flags, reason_code, properties); accept *args defensively.
        self._connected.clear()
        reason = args[-2] if len(args) >= 2 else (args[0] if args else "unknown")
        log.warning("MQTT disconnected (reason=%s); auto-reconnect armed", reason)

    @staticmethod
    def _publish_each(client: Any, messages: Iterable[MQTTMessage]) -> None:
        for topic, payload, retain in messages:
            body = (
                payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
            )
            client.publish(topic, body, qos=_QOS, retain=retain)

    def publish_many(self, messages: Iterable[MQTTMessage]) -> None:
        if self._client is None:
            raise RuntimeError("MQTT publisher is not connected")
        if not self._connected.is_set():
            # Skip this pass instead of raising every cycle during an outage. On
            # reconnect, on_connect re-asserts and the next cycle resends — every
            # message is retained, so nothing is permanently lost.
            log.debug("MQTT not connected; skipping publish of this cycle")
            return
        self._publish_each(self._client, messages)

    def close(self) -> None:
        if self._client is not None:
            # Announce "offline" on graceful shutdown too (the LWT only fires on
            # an ungraceful drop), so HA reflects the bridge state either way.
            with contextlib.suppress(Exception):
                self._client.publish(
                    availability_topic(self.config), "offline", qos=_QOS, retain=True
                ).wait_for_publish()
            self._connected.clear()
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
