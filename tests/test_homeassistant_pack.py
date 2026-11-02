"""The Home Assistant pack must parse and use only entities the MQTT bridge publishes.

The pack lives in ``integrations/home-assistant/pack/``. Its blueprints, dashboard and docs name
Home Assistant entity ids. Those ids are not written down anywhere in the bridge: Home Assistant
derives them from the discovery payload. This test derives them the same way from the bridge's own
discovery messages, so renaming a sensor in the bridge (or making it send ``default_entity_id``)
turns this test red until the pack follows.

Home Assistant's rule, for MQTT entities with a device: ``default_entity_id`` wins when present;
otherwise the entity id is ``<component>.<slug(device name + " " + entity name)>``. The bridge
sends an ``object_id`` too, but Home Assistant ignores it since the 2026.4 release.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant_mqtt.bridge import (
    HomeAssistantMQTTConfig,
    availability_topic,
    build_discovery_messages,
    build_source_discovery_messages,
    sensor_specs_for_config,
)
from homeassistant_mqtt.snapshot import SourceHealthSnapshot

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "integrations" / "home-assistant" / "pack"
BLUEPRINTS = sorted((PACK / "blueprints").glob("*.yaml"))
DASHBOARDS = sorted((PACK / "dashboards").glob("*.yaml"))
DOCS = [PACK / "README.md", ROOT / "docs" / "integrations" / "home-assistant-pack.md"]
SOURCE_URL_PREFIX = (
    "https://github.com/umutkeltek/healthsave-observatory/blob/main/"
    "integrations/home-assistant/pack/blueprints/"
)

# A complete entity id in a sensor-like domain. Placeholders such as ``sensor.observatory_<key>``
# and globs such as ``sensor.healthsave_*`` are deliberately not matched.
ENTITY_ID = re.compile(r"\b(?:sensor|binary_sensor)\.[a-z0-9_]*[a-z0-9](?![a-z0-9_<*])")

# Lovelace cards that ship with Home Assistant. Anything else (``custom:*``) needs HACS.
CORE_CARD_TYPES = {
    "entities",
    "gauge",
    "glance",
    "heading",
    "history-graph",
    "markdown",
    "statistics-graph",
    "tile",
}


class _Input(str):
    """Stands in for a blueprint ``!input`` reference."""


class _BlueprintLoader(yaml.SafeLoader):
    pass


_BlueprintLoader.add_constructor(
    "!input", lambda loader, node: _Input(loader.construct_scalar(node))
)


def _load(path: Path) -> Any:
    return yaml.load(path.read_text(), Loader=_BlueprintLoader)


def _ha_slug(text: str) -> str:
    """Home Assistant's ``slugify`` for the plain ASCII names the bridge uses."""

    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _ha_entity_id(topic: str, payload: dict[str, Any]) -> str:
    if payload.get("default_entity_id"):
        return payload["default_entity_id"]
    component = topic.split("/")[1]
    return f"{component}.{_ha_slug(payload['device']['name'] + ' ' + payload['name'])}"


def _bridge_entity_ids() -> set[str]:
    """Entity ids Home Assistant creates for the bridge's default aggregate device."""

    config = HomeAssistantMQTTConfig()
    messages = build_discovery_messages(config, sensor_specs_for_config(config))
    return {_ha_entity_id(topic, payload) for topic, payload, _retain in messages}


def _example_source_entity_ids() -> set[str]:
    """Entity ids for a per-source device named "Apple Watch", the docs' example."""

    snapshot = SourceHealthSnapshot(
        collected_at=datetime(2026, 11, 2, tzinfo=UTC),
        source_id="Apple Watch",
        heart_rate=60,
        hrv_latest_ms=50.0,
        steps_today=1000,
        last_sleep_hours=7.0,
    )
    messages = build_source_discovery_messages(HomeAssistantMQTTConfig(), snapshot)
    return {_ha_entity_id(topic, payload) for topic, payload, _retain in messages}


def _inputs_used(node: Any) -> set[str]:
    if isinstance(node, _Input):
        return {str(node)}
    if isinstance(node, dict):
        return set().union(*(_inputs_used(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_inputs_used(value) for value in node))
    return set()


def _cards(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every card in a sections-type dashboard."""

    cards: list[dict[str, Any]] = []
    for view in views:
        for section in view.get("sections", []):
            cards.extend(section.get("cards", []))
        cards.extend(view.get("cards", []))
    return cards


def test_pack_ships_three_blueprints_and_a_dashboard() -> None:
    assert [path.name for path in BLUEPRINTS] == [
        "observatory_low_data_warning.yaml",
        "observatory_recovery_aware_morning.yaml",
        "observatory_wind_down_lighting.yaml",
    ]
    assert [path.name for path in DASHBOARDS] == ["observatory_body.yaml"]


def test_bridge_naming_derivation_yields_the_device_prefix() -> None:
    config = HomeAssistantMQTTConfig()
    prefix = f"sensor.{_ha_slug(config.device_name)}_"
    ids = _bridge_entity_ids()

    assert ids
    assert all(entity_id.startswith(prefix) for entity_id in ids)


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda path: path.name)
def test_blueprint_parses_and_declares_every_input(path: Path) -> None:
    doc = _load(path)
    meta = doc["blueprint"]

    assert meta["domain"] == "automation"
    assert meta["name"].startswith("HealthSave Observatory: ")
    assert meta["description"].strip()
    assert meta["source_url"] == SOURCE_URL_PREFIX + path.name
    assert doc.get("triggers") and doc.get("actions")

    declared = meta["input"]
    for name, spec in declared.items():
        assert spec.get("name"), f"{path.name}: input {name} has no name"
        assert "selector" in spec, f"{path.name}: input {name} has no selector"
        if "default" not in spec:
            assert spec.get("description"), f"{path.name}: required input {name} undocumented"

    body = {key: value for key, value in doc.items() if key != "blueprint"}
    used = _inputs_used(body)
    assert used <= set(declared), f"{path.name}: undeclared inputs {sorted(used - set(declared))}"
    assert set(declared) <= used, f"{path.name}: unused inputs {sorted(set(declared) - used)}"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda path: path.name)
def test_blueprint_entities_are_published_by_the_bridge(path: Path) -> None:
    referenced = set(ENTITY_ID.findall(path.read_text()))
    defaults = {
        spec["default"]
        for spec in _load(path)["blueprint"]["input"].values()
        if "entity" in spec["selector"] and spec.get("default")
    }

    assert defaults, f"{path.name} should default to the bridge's entities"
    assert defaults <= referenced
    assert referenced <= _bridge_entity_ids(), sorted(referenced - _bridge_entity_ids())


def test_low_data_blueprint_names_the_bridge_availability_topic() -> None:
    text = (PACK / "blueprints" / "observatory_low_data_warning.yaml").read_text()

    assert availability_topic(HomeAssistantMQTTConfig()) in text


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda path: path.name)
def test_dashboard_parses_and_uses_only_core_cards(path: Path) -> None:
    doc = _load(path)
    views = doc["views"]
    cards = _cards(views)

    assert [view["title"] for view in views] == ["Body"]
    assert cards
    types = {card["type"] for card in cards}
    assert types <= CORE_CARD_TYPES, sorted(types - CORE_CARD_TYPES)
    assert "custom:" not in path.read_text()


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda path: path.name)
def test_dashboard_entities_are_published_by_the_bridge(path: Path) -> None:
    referenced = set(ENTITY_ID.findall(path.read_text()))

    assert referenced
    assert referenced <= _bridge_entity_ids(), sorted(referenced - _bridge_entity_ids())


@pytest.mark.parametrize("path", DOCS, ids=lambda path: path.name)
def test_pack_docs_name_only_published_entities(path: Path) -> None:
    referenced = set(ENTITY_ID.findall(path.read_text()))
    known = _bridge_entity_ids() | _example_source_entity_ids()

    assert referenced <= known, sorted(referenced - known)
