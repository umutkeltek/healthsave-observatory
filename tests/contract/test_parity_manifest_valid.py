"""Parity manifest validity: ``contracts/parity.json`` is well-formed and honest.

The parity manifest is the cross-platform capability ledger: every wire metric
and user-facing feature carries an explicit per-platform availability decision
(``available`` / ``unavailable`` / ``planned``). The client test suites enforce
it from their side (iOS: set-equality against ``HealthTypes`` wire names;
Android: set-equality against the ``MetricCatalog``). This test enforces the
manifest's own honesty rules and runs everywhere — no sibling repo needed:

- ``planned`` requires ``planned_since`` (visible debt, never silent)
- ``unavailable`` requires a non-empty ``reason``
- every metric named by a request-corpus fixture exists in the manifest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "contracts" / "parity.json"
ALLOWED = {"available", "unavailable", "planned"}
PLATFORMS = ("ios", "android")
CORPUS_DIRS = (
    REPO_ROOT / "tests" / "fixtures" / "apple_healthsave",
    REPO_ROOT / "tests" / "fixtures" / "android_healthsave",
)


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def _check_entry(kind: str, name: str, entry: dict) -> list[str]:
    problems: list[str] = []
    for platform in PLATFORMS:
        value = entry.get(platform)
        # Feature entries may use plain booleans for shipped platforms.
        if value is True or value is False:
            continue
        if value not in ALLOWED:
            problems.append(f"{kind} {name}: {platform}={value!r} not in {sorted(ALLOWED)}")
            continue
        if value == "planned" and not entry.get("planned_since"):
            problems.append(f"{kind} {name}: {platform}='planned' without planned_since")
        if value == "unavailable" and not entry.get("reason"):
            problems.append(f"{kind} {name}: {platform}='unavailable' without a reason")
    return problems


def test_manifest_exists_and_versioned() -> None:
    manifest = _manifest()
    assert isinstance(manifest.get("manifest_version"), int)
    assert manifest.get("metrics"), "parity manifest has no metrics block"
    assert manifest.get("features"), "parity manifest has no features block"


def test_every_entry_is_honest() -> None:
    manifest = _manifest()
    problems: list[str] = []
    for name, entry in manifest["metrics"].items():
        problems += _check_entry("metric", name, entry)
    for name, entry in manifest["features"].items():
        problems += _check_entry("feature", name, entry)
    assert not problems, "parity manifest honesty violations:\n" + "\n".join(problems)


@pytest.mark.parametrize("corpus_dir", CORPUS_DIRS, ids=lambda p: p.name)
def test_every_corpus_metric_is_in_manifest(corpus_dir: Path) -> None:
    if not corpus_dir.exists() or not any(corpus_dir.glob("*.json")):
        pytest.skip(f"no request corpus at {corpus_dir.name} yet")
    metrics = set(_manifest()["metrics"])
    missing = {
        payload["metric"]
        for fixture in corpus_dir.glob("*.json")
        if isinstance(payload := json.loads(fixture.read_text()), dict) and "metric" in payload
    } - metrics
    assert not missing, (
        f"request corpus {corpus_dir.name} names metrics absent from "
        f"contracts/parity.json: {sorted(missing)}. Every wire metric is a "
        "recorded parity decision — add them to the manifest and re-mirror."
    )
