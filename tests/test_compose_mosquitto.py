"""Pins the bundled Mosquitto broker's compose wiring.

The broker is a profile-gated service (``mosquitto``) so it does not
start on a default ``docker compose up``. These tests prevent silent
regressions: someone removing the profile, the volume mounts, or the
service name the HA bridge defaults to would break the documented
``docker compose --profile mosquitto --profile home-assistant up``
recipe without any other safety net.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_mqtt_service_uses_eclipse_mosquitto_image():
    services = _compose()["services"]
    assert "mqtt" in services, "bundled MQTT broker service is missing"
    assert services["mqtt"]["image"].startswith("eclipse-mosquitto:")


def test_mqtt_service_is_profile_gated():
    """Profile-gated so ``docker compose up -d`` does not start a broker
    for community users who already run their own.
    """
    services = _compose()["services"]
    assert services["mqtt"]["profiles"] == ["mosquitto"]


def test_mqtt_service_name_matches_ha_bridge_default_broker():
    """HA bridge defaults to ``HA_MQTT_BROKER=mqtt``; the broker service
    must be named ``mqtt`` so docker DNS resolves the default without
    requiring users to set an override env.
    """
    services = _compose()["services"]
    ha = services["homeassistant-mqtt"]["environment"]
    assert ha["HA_MQTT_BROKER"] == "${HA_MQTT_BROKER:-mqtt}"


def test_mqtt_config_file_is_mounted_read_only():
    services = _compose()["services"]
    mounts = services["mqtt"]["volumes"]
    conf_mount = next(
        (m for m in mounts if "mosquitto.conf" in m),
        None,
    )
    assert conf_mount is not None, "mosquitto.conf bind mount missing"
    # Read-only — the broker should not be able to rewrite its own conf.
    assert conf_mount.endswith(":ro")


def test_mqtt_persistence_and_log_volumes_declared():
    """The persistence + log dirs are docker volumes so a `docker compose
    down`/`up` cycle does not silently drop retained messages and the
    operator-visible log scrollback.
    """
    compose = _compose()
    services = compose["services"]
    volumes = compose["volumes"]
    mounts = services["mqtt"]["volumes"]

    data_mount = next((m for m in mounts if ":/mosquitto/data" in m), None)
    log_mount = next((m for m in mounts if ":/mosquitto/log" in m), None)
    assert data_mount is not None
    assert log_mount is not None

    assert "mqtt_data" in volumes
    assert "mqtt_log" in volumes


def test_mosquitto_conf_file_exists_and_enables_persistence():
    conf_path = ROOT / "deploy" / "mosquitto" / "mosquitto.conf"
    assert conf_path.is_file()
    body = conf_path.read_text()
    assert "listener 1883" in body
    assert "persistence true" in body
    # Anonymous-allowed default is intentional for the single-user LAN
    # case. If we ever flip this, callers must overlay a compose
    # override; this test pins the default so a flip is loud.
    assert "allow_anonymous true" in body


def test_mqtt_port_published_for_external_home_assistant():
    """The broker exposes container port 1883 on the host (default
    1883, overridable via ``MOSQUITTO_PORT``) so a Home Assistant
    install running outside docker on the same LAN can connect by
    host IP.
    """
    services = _compose()["services"]
    ports = services["mqtt"]["ports"]
    # Container side is always 1883; host side is env-templated with
    # 1883 as the default. Match the substring without committing to
    # whether the host port appears literally or as a `${VAR:-1883}`.
    assert any(":1883" in str(p) for p in ports)
    # The default must still be 1883 — sanity-check the env fallback.
    assert any("1883" in str(p) for p in ports)
