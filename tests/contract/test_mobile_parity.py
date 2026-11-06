"""Shared native behavior ownership and fail-closed release evidence checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import mobile_parity as mobile

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def test_canonical_mobile_contracts_cover_the_product():
    assert mobile.contract_issues(*mobile.load()) == []
    matrix, _, parity = mobile.load()
    assert set(parity["features"]) <= set(matrix["acceptance"])
    # Availability alone must never claim that the current Android app is equivalent.
    assert mobile.open_issues(matrix, parity)


@pytest.mark.parametrize("sibling", mobile.MIRRORS)
def test_behavior_mirror_is_byte_equal(sibling):
    root = mobile.REPO.parent / sibling
    if not root.is_dir():
        pytest.skip(f"{sibling} is not checked out alongside datahub")
    assert (root / mobile.MIRRORS[sibling]).read_bytes() == (
        mobile.REPO / "contracts/mobile-behavior-cases.json"
    ).read_bytes()


def test_workspace_references_exist():
    if not all((mobile.REPO.parent / sibling).is_dir() for sibling in mobile.MIRRORS):
        pytest.skip("full mobile workspace is not checked out")
    assert mobile.workspace_issues() == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m, c, p: c.pop("csv_escape"),
        lambda m, c, p: c.update(unconsumed=[]),
        lambda m, c, p: c.update(csv_escape=[]),
        lambda m, c, p: c.update(csv_escape=[None]),
        lambda m, c, p: c["csv_escape"].append(c["csv_escape"][0]),
        lambda m, c, p: c["mass_conversion"][0].update(kilograms=True),
        lambda m, c, p: c["mass_conversion"][0].update(tolerance=0),
        lambda m, c, p: c["doctor_access"][0].pop("seconds_since_first_pack"),
        lambda m, c, p: c["relationships"][0]["ys"].pop(),
        lambda m, c, p: c["relationships"][0].update(seed=-1),
        lambda m, c, p: c["relationships"][0]["expected"].update(ci=[0.8, -0.1]),
        lambda m, c, p: c["relationships"][0]["expected"].update(posture="certain"),
        lambda m, c, p: c["relationship_posture"][0].update(q=2),
        lambda m, c, p: c["relationship_posture"][0].update(direction_matches=1),
        lambda m, c, p: c["baselines"][0]["days"].append(c["baselines"][0]["days"][0]),
        lambda m, c, p: c["baselines"][0]["days"][0].__setitem__(1, float("nan")),
        lambda m, c, p: c["baselines"][0]["expected"]["baseline"].update(early=1),
        lambda m, c, p: c["baselines"][0]["expected"]["week"].update(current_valid_days=8),
        lambda m, c, p: c["baselines"][0].update(metric="heart_rate_variability_rmssd"),
        lambda m, c, p: c["recovery"][0]["expected"].update(strain_score=2),
        lambda m, c, p: c["recovery"][0]["expected"].update(aligned_count=4),
        lambda m, c, p: c["recovery"][0]["series"].append(c["recovery"][0]["series"][0]),
        lambda m, c, p: c["theme"].pop(),
        lambda m, c, p: c["theme"][0]["palette"].update(background="invalid"),
        lambda m, c, p: c["theme"][0]["layout"].update(card_corner_radius=-1),
        lambda m, c, p: m["acceptance"].pop("export_csv"),
        lambda m, c, p: m["acceptance"].pop("journey.widgets"),
        lambda m, c, p: m["acceptance"].update({"journey.typo": {}}),
        lambda m, c, p: m["acceptance"]["export_csv"].update(required_evidence=["behavior"]),
        lambda m, c, p: m.update(required_locales=["fake"] * 16),
        lambda m, c, p: m["visual_profiles"].remove("phone-dark"),
    ],
)
def test_contract_drift_is_rejected(mutation):
    contracts = mobile.load()
    mutation(*contracts)
    assert mobile.contract_issues(*contracts)


def save_artifact(root, name, value):
    path = root / name
    path.write_text(json.dumps(value))
    return {"path": name, "sha256": mobile.digest(path)}


@pytest.fixture
def evidence_bundle(tmp_path):
    # Minimal synthetic matrix tests the validator; this is not release evidence.
    matrix = {
        "acceptance": {"example": {"required_evidence": ["behavior", "visual", "device"]}},
        "visual_profiles": ["phone-light", "phone-dark"],
        "required_locales": ["en", "ar"],
    }
    revisions = {name: name * 10 for name in ("ios", "android", "datahub")}
    hashes = {"mobile-behavior-cases.json": "a" * 64}
    native = {
        "schema_version": 1,
        "result": "passed",
        "dirty": False,
        "revisions": revisions,
        "contracts": hashes,
        "observed_at": NOW.isoformat(),
        "commands": {
            name: {"exit_code": 0, "log": save_artifact(tmp_path, f"{name}.log", "fixture")}
            for name in ("workspace", "ios", "android", "ios_locales")
        },
    }
    evidence = {
        "schema_version": 1,
        "revisions": revisions,
        "contracts": hashes,
        "native_verification": save_artifact(tmp_path, "native.json", native),
        "checks": [
            {
                "acceptance_id": "example",
                "platform": platform,
                "kind": kind,
                "result": "passed",
                "reviewer": "Synthetic test fixture",
                "observed_at": NOW.isoformat(),
                "artifact": save_artifact(tmp_path, f"{platform}-{kind}.json", "fixture"),
                "device_kind": "physical",
                "device_os": "test OS",
                "profiles": matrix["visual_profiles"],
                "locales": matrix["required_locales"],
            }
            for platform in ("ios", "android")
            for kind in ("behavior", "visual", "device")
        ],
    }
    return matrix, evidence, tmp_path, revisions, hashes, NOW


def test_complete_synthetic_bundle_satisfies_evidence_structure(evidence_bundle):
    assert mobile.evidence_issues(*evidence_bundle) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e.pop("native_verification"),
        lambda e: e.update(revisions={"ios": "stale"}),
        lambda e: e.update(contracts={"stale": "b" * 64}),
        lambda e: e.update(checks=[]),
        lambda e: e.update(checks=[None]),
        lambda e: e["checks"].append(e["checks"][0]),
        lambda e: e["checks"][0].update(acceptance_id="unknown"),
        lambda e: e["checks"][0].update(platform="other"),
        lambda e: e["checks"][0].update(kind="unsupported"),
        lambda e: e["checks"][0].update(result="failed"),
        lambda e: e["checks"][0].update(reviewer=" "),
        lambda e: e["checks"][0].update(observed_at="2026-11-06T12:00:00"),
        lambda e: e["checks"][0].update(observed_at=(NOW + timedelta(seconds=1)).isoformat()),
        lambda e: e["checks"][0].update(observed_at=(NOW - timedelta(days=31)).isoformat()),
        lambda e: e["checks"][0].update(observed_at=None),
        lambda e: e["checks"][1].update(profiles=["phone-light"]),
        lambda e: e["checks"][1].update(locales=["en"]),
        lambda e: e["checks"][2].update(device_kind="emulator"),
        lambda e: e["checks"][2].update(device_os=""),
        lambda e: e["checks"][0].update(artifact={"path": "missing", "sha256": "a" * 64}),
        lambda e: e["checks"][0]["artifact"].update(sha256="b" * 64),
    ],
)
def test_incomplete_or_invalid_evidence_cannot_pass(evidence_bundle, mutation):
    mutation(evidence_bundle[1])
    assert mobile.evidence_issues(*evidence_bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda n: n.update(dirty=True),
        lambda n: n.update(result="failed"),
        lambda n: n.update(revisions={}),
        lambda n: n.update(contracts={}),
        lambda n: n.update(observed_at=(NOW - timedelta(days=31)).isoformat()),
        lambda n: n["commands"].pop("ios"),
        lambda n: n["commands"]["android"].update(exit_code=1),
        lambda n: n["commands"]["android"].update(exit_code=False),
        lambda n: n["commands"]["ios"].update(log={}),
    ],
)
def test_native_proof_must_be_complete_and_current(evidence_bundle, mutation):
    _, evidence, root, *_ = evidence_bundle
    native = json.loads((root / "native.json").read_text())
    mutation(native)
    evidence["native_verification"] = save_artifact(root, "native.json", native)
    assert mobile.evidence_issues(*evidence_bundle)


def test_evidence_artifacts_cannot_escape_bundle(evidence_bundle):
    _, evidence, root, *_ = evidence_bundle
    outside = root.parent / "outside-evidence.json"
    outside.write_text("fixture")
    evidence["checks"][0]["artifact"] = {
        "path": "../outside-evidence.json",
        "sha256": mobile.digest(outside),
    }
    assert mobile.evidence_issues(*evidence_bundle)
    (root / "link.json").symlink_to(outside)
    evidence["checks"][0]["artifact"]["path"] = "link.json"
    assert mobile.evidence_issues(*evidence_bundle)


def test_evidence_detects_tampered_logs(evidence_bundle):
    (evidence_bundle[2] / "ios.log").write_text("changed after verification")
    assert mobile.evidence_issues(*evidence_bundle)


def test_behavior_mirror_whitespace_drift_fails(tmp_path):
    repo = tmp_path / "datahub"
    (repo / "contracts").mkdir(parents=True)
    (repo / "contracts/mobile-behavior-cases.json").write_text("{}")
    for name in ("mobile-acceptance.json", "parity.json"):
        (repo / "contracts" / name).write_text('{"acceptance": {}}')
    for sibling, name in mobile.MIRRORS.items():
        path = tmp_path / sibling / name
        path.parent.mkdir(parents=True)
        path.write_text("{}\n")
    assert len(mobile.workspace_issues(repo)) == 2


def test_verify_refuses_output_in_source_tree(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        mobile.verify(tmp_path / "datahub", tmp_path / "ios_app/evidence", "unused")
