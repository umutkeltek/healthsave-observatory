"""Shared mobile contract checks, native verification and release-evidence validation.

Availability is not equivalence. This tool never grants permission to publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLATFORMS = {"ios": "ios_app", "android": "android_app"}
SUITES = {
    "csv_escape",
    "mass_conversion",
    "doctor_access",
    "theme",
    "relationships",
    "relationship_posture",
    "baselines",
    "recovery",
}
JOURNEYS = {
    "journey.onboarding",
    "journey.purchase_restore",
    "journey.permission_states",
    "journey.visual_system",
    "journey.insights",
    "journey.widgets",
}
LOCALES = {
    "en",
    "de",
    "es",
    "it",
    "fr",
    "ja",
    "ko",
    "zh-Hans",
    "zh-Hant",
    "ar",
    "tr",
    "nl",
    "pt-BR",
    "pl",
    "id",
    "th",
}
PROFILES = {
    "phone-light",
    "phone-dark",
    "phone-large-text",
    "phone-arabic-rtl",
    "tablet-portrait",
    "tablet-landscape",
}
MIRRORS = {
    "ios_app": "Tests/HealthSyncTests/Fixtures/mobile-behavior-cases.json",
    "android_app": "contract/src/test/resources/fixtures/mobile-behavior-cases.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


BASELINE_METRICS = {
    "resting_heart_rate",
    "respiratory_rate",
    "sleep_duration",
    "steps",
    "active_energy_burned",
    "body_mass",
    "vo2_max",
}


def valid_daily_series(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(row, list) and len(row) == 2 and type(row[0]) is int and number(row[1])
            for row in value
        )
        and len({row[0] for row in value}) == len(value)
    )


def valid_baseline_case(row: dict) -> bool:
    expected = row.get("expected")
    if not (
        row.get("metric") in BASELINE_METRICS
        and valid_daily_series(row.get("days"))
        and isinstance(expected, dict)
        and type(expected.get("anomaly")) is bool
        and "baseline" in expected
    ):
        return False
    baseline, week = expected["baseline"], expected.get("week")
    valid_baseline = baseline is None or (
        isinstance(baseline, dict)
        and all(number(baseline.get(k)) for k in ("value", "median", "robust_sd", "z"))
        and baseline["robust_sd"] >= 0
        and "percent_delta" in baseline
        and (baseline["percent_delta"] is None or number(baseline["percent_delta"]))
        and type(baseline.get("valid_days")) is int
        and 0 <= baseline["valid_days"] <= 60
        and all(
            type(baseline.get(k)) is bool for k in ("early", "spread_suppressed", "passes_floor")
        )
        and baseline.get("posture") in {"descriptive", "insufficientData"}
        and baseline.get("label")
        in {"usual", "aBitOutside", "notablyOutside", "unusualForYou", "veryUnusualForYou"}
    )
    return valid_baseline and (
        isinstance(week, dict)
        and all(
            number(week.get(k))
            for k in ("current_median", "baseline_median", "robust_sd", "d_robust")
        )
        and week["robust_sd"] >= 0
        and type(week.get("current_valid_days")) is int
        and 0 <= week["current_valid_days"] <= 7
        and type(week.get("baseline_valid_days")) is int
        and 0 <= week["baseline_valid_days"] <= 56
        and week.get("posture") in {"descriptive", "insufficientData"}
        and week.get("label") in {"none", "small", "modest", "notable", "largeForYou"}
    )


def valid_recovery_case(row: dict) -> bool:
    series, expected = row.get("series"), row.get("expected")
    if not (isinstance(series, list) and isinstance(expected, dict)):
        return False
    metrics = {"resting_heart_rate", "respiratory_rate", "sleep_duration"}
    if not all(
        isinstance(s, dict) and s.get("metric") in metrics and valid_daily_series(s.get("days"))
        for s in series
    ):
        return False
    if len({s["metric"] for s in series}) != len(series):
        return False
    contributions = expected.get("contributions")
    return (
        isinstance(contributions, list)
        and all(
            isinstance(c, dict)
            and c.get("metric") in metrics
            and all(number(c.get(k)) for k in ("raw_z", "strain_z"))
            and type(c.get("passes_floor")) is bool
            for c in contributions
        )
        and len({c["metric"] for c in contributions}) == len(contributions)
        and number(expected.get("strain_score"))
        and 0 <= expected["strain_score"] <= 1
        and type(expected.get("signal_count")) is int
        and expected["signal_count"] == len(contributions)
        and type(expected.get("aligned_count")) is int
        and 0 <= expected["aligned_count"] <= expected["signal_count"]
        and all(type(expected.get(k)) is bool for k in ("toward_strain", "qualifies"))
        and expected.get("posture") in {"descriptive", "noFinding", "insufficientData"}
    )


def valid_relationship_ci(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(number(bound) for bound in value)
        and -1 <= value[0] <= value[1] <= 1
    )


def valid_relationship_result(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(number(value.get(key)) for key in ("rho", "effective_n", "p", "sign_probability"))
        and -1 <= value["rho"] <= 1
        and value["effective_n"] >= 0
        and 0 <= value["p"] <= 1
        and 0 <= value["sign_probability"] <= 1
        and "ci" in value
        and (value["ci"] is None or valid_relationship_ci(value["ci"]))
        and value.get("posture")
        in {"personalPattern", "earlyHint", "noFinding", "insufficientData"}
    )


def same_members(value: object, expected) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and set(value) == set(expected)
    )


def load(repo: Path = REPO) -> tuple[dict, dict, dict]:
    return tuple(
        json.loads((repo / "contracts" / name).read_text())
        for name in ("mobile-acceptance.json", "mobile-behavior-cases.json", "parity.json")
    )


def contract_issues(matrix: dict, cases: dict, parity: dict) -> list[str]:
    issues = []
    if not all(isinstance(value, dict) for value in (matrix, cases, parity)):
        return ["Contracts must be JSON objects"]
    if matrix.get("schema_version") != 1 or matrix.get("reference_platform") != "ios":
        issues.append("Acceptance contract must use schema 1 and the iOS reference")
    if set(cases) != SUITES | {"schema_version"} or cases.get("schema_version") != 1:
        issues.append("Shared behavior suites changed; update both native consumers")
    for suite in SUITES:
        rows = cases.get(suite, [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            issues.append(f"{suite}: cases must be objects")
            continue
        ids = [row.get("id") for row in rows]
        if suite == "theme" and not same_members(ids, {"light", "dark"}):
            issues.append("Theme cases must cover both light and dark appearances")
        if (
            not rows
            or not all(isinstance(key, str) and key.strip() for key in ids)
            or len(ids) != len(set(ids))
        ):
            issues.append(f"{suite}: cases need unique nonempty IDs")
        for row in rows:
            if suite == "csv_escape":
                valid = all(isinstance(row.get(key), str) for key in ("input", "expected"))
            elif suite == "mass_conversion":
                valid = (
                    row.get("unit") in ("kg", "lb", "st")
                    and all(number(row.get(key)) for key in ("kilograms", "expected", "tolerance"))
                    and row["tolerance"] > 0
                )
            elif suite == "relationship_posture":
                ci = row.get("ci")
                valid = (
                    all(number(row.get(key)) for key in ("rho", "effective_n", "sign_probability"))
                    and -1 <= row["rho"] <= 1
                    and row["effective_n"] >= 0
                    and 0 <= row["sign_probability"] <= 1
                    and "ci" in row
                    and (ci is None or valid_relationship_ci(ci))
                    and "q" in row
                    and (row["q"] is None or (number(row["q"]) and 0 <= row["q"] <= 1))
                    and type(row.get("direction_matches")) is bool
                    and row.get("expected") in {"personalPattern", "earlyHint", "noFinding"}
                )
            elif suite == "relationships":
                xs, ys, expected = row.get("xs"), row.get("ys"), row.get("expected")
                valid = (
                    isinstance(xs, list)
                    and isinstance(ys, list)
                    and bool(xs)
                    and len(xs) == len(ys)
                    and all(number(value) for value in xs + ys)
                    and type(row.get("expected_positive")) is bool
                    and type(row.get("seed")) is int
                    and 0 <= row["seed"] < 2**63
                    and "expected" in row
                    and (expected is None or valid_relationship_result(expected))
                )
            elif suite == "baselines":
                valid = valid_baseline_case(row)
            elif suite == "recovery":
                valid = valid_recovery_case(row)
            elif suite == "theme":
                colors = row.get("palette", {})
                layout = row.get("layout", {})
                valid = (
                    row.get("id") in ("light", "dark")
                    and isinstance(colors, dict)
                    and isinstance(layout, dict)
                    and bool(colors)
                    and bool(layout)
                    and all(
                        isinstance(value, str) and re.fullmatch(r"#[0-9A-F]{6}", value)
                        for value in colors.values()
                    )
                    and all(number(value) and value > 0 for value in layout.values())
                )
            else:
                valid = all(type(row.get(key)) is bool for key in ("is_pro", "expected")) and (
                    "seconds_since_first_pack" in row
                    and (
                        row["seconds_since_first_pack"] is None
                        or number(row["seconds_since_first_pack"])
                    )
                )
            if not valid:
                issues.append(f"{suite}: invalid case {row.get('id')}")
    acceptance = matrix.get("acceptance", {})
    if not isinstance(acceptance, dict) or not isinstance(parity.get("features"), dict):
        return issues + ["Acceptance and features must be objects"]
    missing = (set(parity["features"]) | JOURNEYS) - set(acceptance)
    unknown = set(acceptance) - set(parity["features"]) - JOURNEYS
    issues += [f"Feature lacks paired acceptance criteria: {key}" for key in sorted(missing)]
    issues += [f"Unknown feature ID: {key}" for key in sorted(unknown)]
    for key, row in acceptance.items():
        if not isinstance(row, dict):
            issues.append(f"{key}: acceptance must be an object")
            continue
        if not all(
            isinstance(row.get(field), str) and row[field].strip()
            for field in ("expected", "ios_source")
        ):
            issues.append(f"{key}: expected behavior and iOS reference are required")
        kinds = row.get("required_evidence", [])
        if not (
            same_members(kinds, {"behavior", "visual"})
            or same_members(kinds, {"behavior", "visual", "device"})
        ):
            issues.append(f"{key}: invalid evidence requirements")
    gaps = matrix.get("open_gaps", [])
    if not isinstance(gaps, list) or not all(isinstance(row, dict) for row in gaps):
        return issues + ["Open gaps must be objects"]
    gap_ids = [row.get("id") for row in gaps]
    if not all(isinstance(key, str) and key.strip() for key in gap_ids):
        issues.append("Gap IDs must be nonempty strings")
    elif len(gap_ids) != len(set(gap_ids)):
        issues.append("Duplicate gap IDs")
    for gap in gaps:
        if gap.get("acceptance_id") not in acceptance or not gap.get("detail"):
            issues.append(f"Invalid gap: {gap.get('id')}")
    if not same_members(matrix.get("visual_profiles"), PROFILES) or not same_members(
        matrix.get("required_locales"), LOCALES
    ):
        issues.append("The shared visual profiles and 16-language baseline are required")
    return issues


def workspace_issues(repo: Path = REPO) -> list[str]:
    matrix, _, _ = load(repo)
    issues = []
    canonical = (repo / "contracts/mobile-behavior-cases.json").read_bytes()
    for sibling, mirror in MIRRORS.items():
        path = repo.parent / sibling / mirror
        if not path.exists() or path.read_bytes() != canonical:
            issues.append(f"Missing or nonidentical behavior mirror: {sibling}/{mirror}")
    for key, row in matrix["acceptance"].items():
        for platform, sibling in PLATFORMS.items():
            ref = row.get(f"{platform}_source")
            base = (repo.parent / sibling).resolve()
            path = (base / ref).resolve() if ref else None
            if path and (not path.is_relative_to(base) or not path.is_file()):
                issues.append(f"{key}: missing or invalid {platform} reference {ref}")
    return issues


def open_issues(matrix: dict, parity: dict) -> list[str]:
    issues = [f"{gap['id']}: {gap['detail']}" for gap in matrix["open_gaps"]]
    pending = [key for key, row in parity["metrics"].items() if row["android"] == "planned"]
    if pending:
        issues.append(
            f"{len(pending)} Android metrics still planned; "
            "classify or implement each with semantic evidence"
        )
    for key, row in parity["features"].items():
        if row.get("ios") is True and row.get("android") is not True:
            issues.append(f"Platform feature difference still needs explicit review: {key}")
    return issues


def artifact(ref: dict, root: Path) -> Path:
    """Evidence stays within its declared bundle and must match its captured hash."""
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValueError("artifact must declare a path and SHA256")
    path = (root / ref["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("artifact missing or outside evidence bundle")
    if not re.fullmatch(r"[0-9a-f]{64}", ref.get("sha256", "")) or digest(path) != ref["sha256"]:
        raise ValueError("artifact hash does not match")
    return path


def recent(value: str, now: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return captured.tzinfo is not None and timedelta(0) <= now - captured <= timedelta(days=30)
    except ValueError:
        return False


def evidence_issues(
    matrix: dict, evidence: dict, root: Path, revisions: dict, hashes: dict, now: datetime
) -> list[str]:
    issues = []
    if not isinstance(evidence, dict):
        return ["Evidence must be an object"]
    if evidence.get("schema_version") != 1:
        issues.append("Evidence schema must be 1")
    if evidence.get("revisions") != revisions or evidence.get("contracts") != hashes:
        issues.append("Evidence is stale for the candidate revisions or shared contracts")
    try:
        native = json.loads(artifact(evidence["native_verification"], root).read_text())
        if not isinstance(native, dict) or native.get("schema_version") != 1:
            raise ValueError("native verification must use schema 1")
        if not recent(native.get("observed_at"), now):
            issues.append("Native verification is future-dated or older than 30 days")
        if native.get("result") != "passed" or native.get("dirty") is not False:
            issues.append("Native verification must pass on clean candidate revisions")
        if native.get("revisions") != revisions or native.get("contracts") != hashes:
            issues.append("Native verification is not bound to this candidate")
        if set(native.get("commands", {})) != {"workspace", "android", "ios", "ios_locales"}:
            issues.append("Native verification is missing a required suite")
        for name, command in native.get("commands", {}).items():
            if type(command.get("exit_code")) is not int or command["exit_code"] != 0:
                issues.append(f"Native suite failed: {name}")
            artifact(command["log"], root)
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
        issues.append(f"Invalid native verification: {exc}")
    observed = set()
    checks = evidence.get("checks", [])
    if not isinstance(checks, list) or not all(isinstance(row, dict) for row in checks):
        return issues + ["Checks must be a list of evidence objects"]
    for row in checks:
        key = (row.get("acceptance_id"), row.get("platform"), row.get("kind"))
        if not all(isinstance(value, str) for value in key):
            issues.append("Evidence target must contain strings")
            continue
        if key in observed:
            issues.append(f"Duplicate evidence: {key}")
        observed.add(key)
        if key[0] not in matrix["acceptance"] or key[1] not in PLATFORMS:
            issues.append(f"Unknown evidence target: {key}")
            continue
        if key[2] not in matrix["acceptance"][key[0]]["required_evidence"]:
            issues.append(f"Unexpected evidence kind: {key}")
        if (
            row.get("result") != "passed"
            or not isinstance(row.get("reviewer"), str)
            or not row["reviewer"].strip()
        ):
            issues.append(f"Evidence has no passing reviewed result: {key}")
        try:
            if not recent(row.get("observed_at"), now):
                issues.append(f"Evidence is future-dated or older than 30 days: {key}")
            artifact(row["artifact"], root)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            issues.append(f"Invalid evidence {key}: {exc}")
        if key[2] == "device" and (
            row.get("device_kind") != "physical" or not row.get("device_os")
        ):
            issues.append(f"Physical device and OS evidence required: {key}")
        if key[2] == "visual" and not same_members(row.get("profiles"), matrix["visual_profiles"]):
            issues.append(f"Visual profiles incomplete: {key}")
        if key[2] == "visual" and not same_members(row.get("locales"), matrix["required_locales"]):
            issues.append(f"Visual locale review incomplete: {key}")
    expected = {
        (key, platform, kind)
        for key, item in matrix["acceptance"].items()
        for platform in PLATFORMS
        for kind in item["required_evidence"]
    }
    issues += [f"Missing evidence: {key}" for key in sorted(expected - observed)]
    return issues


def candidate(repo: Path) -> tuple[dict, dict, bool]:
    paths = {**{p: repo.parent / sibling for p, sibling in PLATFORMS.items()}, "datahub": repo}
    revisions = {
        p: subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
        for p, path in paths.items()
    }
    dirty = any(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=path).strip()
        for path in paths.values()
    )
    hashes = {
        name: digest(repo / "contracts" / name)
        for name in ("mobile-acceptance.json", "mobile-behavior-cases.json", "parity.json")
    }
    return revisions, hashes, dirty


def source_state(repo: Path) -> str:
    """Detect source edits during a development run, including uncommitted files."""
    result = hashlib.sha256()
    for path in [repo, *(repo.parent / sibling for sibling in PLATFORMS.values())]:
        result.update(subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=path))
        untracked = (
            subprocess.check_output(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=path
            )
            .decode()
            .split("\0")
        )
        for name in sorted(filter(None, untracked)):
            result.update(name.encode())
            result.update((path / name).read_bytes())
    return result.hexdigest()


def verify(repo: Path, output: Path, destination: str) -> int:
    if any(
        output.resolve().is_relative_to(path.resolve())
        for path in [repo, *(repo.parent / sibling for sibling in PLATFORMS.values())]
    ):
        raise ValueError("Verification output must be outside the three source repositories")
    output.mkdir(parents=True, exist_ok=False)
    revisions, hashes, dirty = candidate(repo)
    before = source_state(repo)
    environment = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    commands = {
        "workspace": (repo.parent, ["make", "trust-fast"]),
        "android": (repo.parent / "android_app", ["./gradlew", "check"]),
        "ios": (
            repo.parent / "ios_app",
            [
                "xcodebuild",
                "test",
                "-project",
                "HealthSync.xcodeproj",
                "-scheme",
                "HealthSync",
                "-destination",
                destination,
                "-parallel-testing-enabled",
                "NO",
                "-quiet",
            ],
        ),
        "ios_locales": (repo.parent / "ios_app", ["node", "Tools/l10n_preflight.mjs"]),
    }
    results = {}
    for name, (cwd, command) in commands.items():
        print(f"Running {name}: {' '.join(command)}", flush=True)
        log = output / f"{name}.log"
        with log.open("w") as stream:
            result = subprocess.run(
                command,
                cwd=cwd,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                env=environment,
            )
        results[name] = {
            "argv": command,
            "exit_code": result.returncode,
            "log": {"path": log.name, "sha256": digest(log)},
        }
        print(f"{name}: exit {result.returncode}; log {log}", flush=True)
    end_revisions, end_hashes, end_dirty = candidate(repo)
    passed = (
        all(row["exit_code"] == 0 for row in results.values())
        and (revisions, hashes)
        == (
            end_revisions,
            end_hashes,
        )
        and before == source_state(repo)
    )
    receipt = {
        "schema_version": 1,
        "result": "passed" if passed else "failed",
        "revisions": revisions,
        "contracts": hashes,
        "dirty": dirty or end_dirty,
        "source_state": before,
        "commands": results,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    (output / "native-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        "Native checks passed; parity and device review remain separate."
        if passed
        else "Native verification failed or source revisions changed."
    )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "report", "verify", "release-check"])
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--ios-destination", default="platform=iOS Simulator,name=iPhone 17 Pro")
    args = parser.parse_args()
    try:
        matrix, cases, parity = load()
        issues = contract_issues(matrix, cases, parity) + workspace_issues()
        if issues:
            print("\n".join(issues), file=sys.stderr)
            return 1
        if args.command == "check":
            print("Shared mobile contracts and mirrors valid. This is not proof of product parity.")
            return 0
        if args.command == "verify":
            if args.output_dir is None:
                parser.error("verify requires a new --output-dir")
            return verify(REPO, args.output_dir.resolve(), args.ios_destination)
        issues = open_issues(matrix, parity)
        if args.command == "release-check":
            revisions, hashes, dirty = candidate(REPO)
            if dirty:
                issues.append("Candidate repositories are dirty")
            if args.evidence is None:
                issues.append("No paired release evidence bundle supplied")
            else:
                evidence = json.loads(args.evidence.read_text())
                issues += evidence_issues(
                    matrix, evidence, args.evidence.parent, revisions, hashes, datetime.now(UTC)
                )
        print(
            f"iOS-reference acceptance: {len(matrix['acceptance'])} scenarios; "
            f"{len(issues)} unresolved items"
        )
        for issue in issues:
            print(f"- {issue}")
        if args.command == "release-check":
            print(
                "RELEASE PARITY BLOCKED"
                if issues
                else "Evidence requirements satisfied. Operator release approval is still required."
            )
            return 1 if issues else 0
        return 0
    except (AttributeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Invalid or unavailable parity evidence: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
