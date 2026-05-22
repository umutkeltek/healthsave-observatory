"""Docs should describe the shipped surface, not an older migration state."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_and_bridge_list_all_shipped_grafana_dashboards():
    readme = (ROOT / "README.md").read_text()
    bridge = (ROOT / "BRIDGE.md").read_text()

    for text in (readme, bridge):
        for expected in (
            "HealthSave Overview",
            "Activity & Movement",
            "Heart",
            "Sleep",
            "Insights",
            "Workouts",
        ):
            assert expected in text

    assert "Three auto-provisioned Grafana dashboards" not in bridge


def test_source_plugin_readmes_match_worker_and_ingest_state():
    whoop = (ROOT / "plugins" / "sources" / "whoop" / "README.md").read_text()
    amazfit = (ROOT / "plugins" / "sources" / "amazfit" / "README.md").read_text()

    assert "worker scheduler registration" not in whoop
    assert "remaining piece" not in whoop
    assert "raises `NotImplementedError`" not in amazfit
    assert "H-ingest ships" in amazfit
