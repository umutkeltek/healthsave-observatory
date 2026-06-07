"""Unit tests for the paho wrapper's resilience + Last-Will behaviour.

The bridge previously (1) connected with no LWT, so a crashed bridge left Home
Assistant showing the last retained value as if it were live, and (2) announced
availability "online" only once at startup — so after a broker blip the retained
LWT "offline" stuck and HA went dark even once the socket recovered.

These tests pin the wrapper's resilience contract:
- registers an "offline" LWT on the availability topic *before* connecting,
- connects asynchronously with bounded-backoff auto-reconnect,
- re-asserts availability "online" + discovery on *every* (re)connect,
- skips publishing (rather than raising) while disconnected,
- announces "offline" on graceful close.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig, availability_topic
from homeassistant_mqtt.client import PahoMQTTPublisher


def _install_fake_paho(monkeypatch, fake_client: MagicMock) -> None:
    """Inject a fake ``paho.mqtt.client`` so ``connect()`` is unit-testable."""

    class _CallbackAPIVersion:
        VERSION2 = 2

    mqtt_mod = types.ModuleType("paho.mqtt.client")
    mqtt_mod.CallbackAPIVersion = _CallbackAPIVersion  # type: ignore[attr-defined]
    mqtt_mod.Client = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", mqtt_mod)


def test_connect_registers_offline_lwt_before_connect(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    fake_client = MagicMock()
    _install_fake_paho(monkeypatch, fake_client)

    PahoMQTTPublisher(config).connect()

    fake_client.will_set.assert_called_once_with(
        availability_topic(config), payload="offline", qos=0, retain=True
    )
    call_order = [name for name, *_ in fake_client.method_calls]
    # connect_async (not connect) so a not-yet-up broker doesn't crash the bridge.
    assert call_order.index("will_set") < call_order.index("connect_async")


def test_connect_arms_autoreconnect_and_background_loop(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    fake_client = MagicMock()
    _install_fake_paho(monkeypatch, fake_client)

    PahoMQTTPublisher(config).connect()

    fake_client.reconnect_delay_set.assert_called_once()
    fake_client.connect_async.assert_called_once()
    fake_client.loop_start.assert_called_once()
    # Resilience callbacks must be wired so reconnects re-assert availability.
    assert fake_client.on_connect is not None
    assert fake_client.on_disconnect is not None


def test_on_connect_reasserts_online_and_discovery(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    avail = availability_topic(config)
    session = [
        (avail, "online", True),
        ("homeassistant/sensor/healthsave/heart_rate/config", {"name": "HR"}, True),
    ]
    publisher = PahoMQTTPublisher(config, on_connect_messages=lambda: list(session))
    fake_client = MagicMock()

    # reason_code 0 == success (int fallback path).
    publisher._on_connect(fake_client, None, None, 0)

    published_topics = [call.args[0] for call in fake_client.publish.call_args_list]
    assert avail in published_topics
    assert "homeassistant/sensor/healthsave/heart_rate/config" in published_topics
    # online payload stays a plain string; dict discovery payload is JSON-encoded.
    online_calls = [c for c in fake_client.publish.call_args_list if c.args[0] == avail]
    assert online_calls[0].args[1] == "online"
    assert publisher._connected.is_set()


def test_on_connect_failure_does_not_publish_or_mark_connected(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    publisher = PahoMQTTPublisher(config, on_connect_messages=lambda: [("t", "online", True)])
    fake_client = MagicMock()

    refused = types.SimpleNamespace(is_failure=True)
    publisher._on_connect(fake_client, None, None, refused)

    fake_client.publish.assert_not_called()
    assert not publisher._connected.is_set()


def test_publish_many_skips_while_disconnected(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    publisher = PahoMQTTPublisher(config)
    fake_client = MagicMock()
    publisher._client = fake_client  # simulate connected wrapper, socket down

    publisher.publish_many([("t", {"v": 1}, True)])

    fake_client.publish.assert_not_called()


def test_publish_many_sends_when_connected(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    publisher = PahoMQTTPublisher(config)
    fake_client = MagicMock()
    publisher._client = fake_client
    publisher._connected.set()

    publisher.publish_many([("t", {"v": 1}, True)])

    fake_client.publish.assert_called_once_with("t", '{"v":1}', qos=0, retain=True)


def test_close_announces_offline(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    fake_client = MagicMock()
    _install_fake_paho(monkeypatch, fake_client)

    publisher = PahoMQTTPublisher(config)
    publisher.connect()
    publisher.close()

    published_topics = [call.args[0] for call in fake_client.publish.call_args_list]
    assert availability_topic(config) in published_topics
