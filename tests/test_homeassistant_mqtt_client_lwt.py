"""Unit tests for the paho wrapper's Last-Will-and-Testament behaviour.

The bridge previously connected with no LWT, so a crashed/killed bridge left
Home Assistant showing the last retained value as if it were live. These tests
pin that the wrapper now registers an "offline" will on the availability topic
*before* CONNECT, and also announces offline on graceful close.
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
    assert call_order.index("will_set") < call_order.index("connect")


def test_close_announces_offline(monkeypatch) -> None:
    config = HomeAssistantMQTTConfig(broker="b", port=1883, state_topic_prefix="healthsave")
    fake_client = MagicMock()
    _install_fake_paho(monkeypatch, fake_client)

    publisher = PahoMQTTPublisher(config)
    publisher.connect()
    publisher.close()

    published_topics = [call.args[0] for call in fake_client.publish.call_args_list]
    assert availability_topic(config) in published_topics
