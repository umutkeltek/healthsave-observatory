from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NPM_PACKAGE = ROOT / "packages" / "npm" / "healthsave-observatory"
BIN = NPM_PACKAGE / "bin" / "healthsave-observatory.mjs"


def _require_node() -> None:
    if not shutil.which("node"):
        pytest.skip("node is required for npm CLI package tests")


def _require_npm() -> None:
    if not shutil.which("npm"):
        pytest.skip("npm is required for npm CLI package tests")


def _require_npx() -> None:
    if not shutil.which("npx"):
        pytest.skip("npx is required for npm CLI package tests")


def test_node_cli_help_explains_npx_setup() -> None:
    _require_node()

    proc = subprocess.run(
        ["node", str(BIN), "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "npx healthsave setup basic" in proc.stdout
    assert "healthsave tui" in proc.stdout
    assert "healthsave init" in proc.stdout
    assert "healthsave-observatory is installed by the same npm package" in proc.stdout
    assert "--dir DIR" in proc.stdout


def test_node_cli_init_dry_run_is_non_mutating(tmp_path: Path) -> None:
    _require_node()

    target = tmp_path / "stack"
    proc = subprocess.run(
        ["node", str(BIN), "init", str(target), "--dry-run"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Would clone" in proc.stdout
    assert "Would install wrapper command: healthsave" in proc.stdout
    assert not target.exists()


def test_npm_exec_runs_packaged_healthsave_bin() -> None:
    _require_npm()

    proc = subprocess.run(
        [
            "npm",
            "exec",
            "--yes",
            "--package",
            str(NPM_PACKAGE),
            "--",
            "healthsave",
            "--version",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )

    assert proc.stdout.strip() == "healthsave 0.1.0"


def test_npx_package_delegates_to_existing_checkout_layers_json() -> None:
    _require_npx()

    proc = subprocess.run(
        [
            "npx",
            "--yes",
            "--package",
            str(NPM_PACKAGE),
            "healthsave",
            "layers",
            "--dir",
            str(ROOT),
            "--json",
        ],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert "api" in payload["layers"]
    assert "grafana" in payload["layers"]


def test_node_cli_preserves_delegated_log_layer_argument(tmp_path: Path) -> None:
    _require_node()

    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (stack / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    healthsave = stack / "healthsave"
    healthsave.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > delegated-args.txt\n",
        encoding="utf-8",
    )
    healthsave.chmod(healthsave.stat().st_mode | stat.S_IXUSR)

    subprocess.run(
        ["node", str(BIN), "logs", "--dir", str(stack), "api"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "logs",
        "api",
    ]


def test_node_cli_delegates_tui_command(tmp_path: Path) -> None:
    _require_node()

    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (stack / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    healthsave = stack / "healthsave"
    healthsave.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > delegated-args.txt\n",
        encoding="utf-8",
    )
    healthsave.chmod(healthsave.stat().st_mode | stat.S_IXUSR)

    subprocess.run(
        ["node", str(BIN), "tui", "--dir", str(stack)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "tui",
    ]
