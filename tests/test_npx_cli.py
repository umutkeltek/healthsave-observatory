from __future__ import annotations

import json
import os
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


def _fake_checkout(tmp_path: Path) -> Path:
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
    return stack


def test_node_cli_help_explains_onboard_flow() -> None:
    _require_node()

    proc = subprocess.run(
        ["node", str(BIN), "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "npm i -g healthsave" in proc.stdout
    assert "healthsave onboard" in proc.stdout
    assert "npx healthsave" in proc.stdout
    assert "healthsave init" in proc.stdout
    assert "healthsave version" in proc.stdout
    assert "healthsave-observatory is installed by the same npm package" in proc.stdout
    assert "--dir DIR" in proc.stdout


def test_node_cli_version_command() -> None:
    _require_node()

    proc = subprocess.run(
        ["node", str(BIN), "--version"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert proc.stdout.strip() == "healthsave 0.1.2"

    components = subprocess.run(
        ["node", str(BIN), "version", "--dir", str(ROOT), "--json"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    payload = json.loads(components.stdout)
    assert payload["bootstrapper"]["version"] == "0.1.2"
    assert payload["bootstrapper"]["default_ref"] == "v0.1.2"
    assert payload["checkout"]["core_version"] == "healthsave 0.3.0"


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
    assert "Would checkout ref v0.1.2" in proc.stdout
    assert "Would install wrapper command" not in proc.stdout
    assert not target.exists()

    with_wrapper = subprocess.run(
        ["node", str(BIN), "init", str(target), "--dry-run", "--install-cli"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    assert "Would install wrapper command: healthsave" in with_wrapper.stdout


def test_node_cli_bare_dry_run_opens_onboard_flow(tmp_path: Path) -> None:
    _require_node()
    target = tmp_path / "stack"
    proc = subprocess.run(
        ["node", str(BIN), "--dry-run"],
        cwd="/tmp",
        env={**os.environ, "HEALTHSAVE_OBSERVATORY_HOME": str(target)},
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Would clone" in proc.stdout
    assert str(target) in proc.stdout
    assert "Would open interactive control center: healthsave onboard" in proc.stdout
    assert not target.exists()


def test_node_cli_onboard_dry_run_clones_before_opening_onboard(tmp_path: Path) -> None:
    _require_node()
    target = tmp_path / "stack"
    proc = subprocess.run(
        ["node", str(BIN), "onboard", "--dry-run", "--dir", str(target)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Would clone" in proc.stdout
    assert str(target) in proc.stdout
    assert "Would open interactive control center: healthsave onboard" in proc.stdout
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

    assert proc.stdout.strip() == "healthsave 0.1.2"


def test_npm_packed_global_install_uses_real_healthsave_shim(tmp_path: Path) -> None:
    _require_npm()
    if os.name == "nt":
        pytest.skip("isolated npm prefix shim path differs on Windows")

    pack = subprocess.run(
        ["npm", "pack", "--pack-destination", str(tmp_path)],
        cwd=NPM_PACKAGE,
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    tarball = tmp_path / pack.stdout.strip().splitlines()[-1]
    prefix = tmp_path / "prefix"
    home = tmp_path / "home"
    prefix.mkdir()
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "npm_config_prefix": str(prefix)}

    subprocess.run(
        ["npm", "install", "--global", "--prefix", str(prefix), str(tarball)],
        cwd="/tmp",
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    proc = subprocess.run(
        [str(prefix / "bin" / "healthsave"), "--version"],
        cwd="/tmp",
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert proc.stdout.strip() == "healthsave 0.1.2"


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


def test_node_cli_init_does_not_self_collide_with_path_shim(tmp_path: Path) -> None:
    _require_node()
    path_bin = tmp_path / "path-bin"
    path_bin.mkdir()
    shim = path_bin / "healthsave"
    shim.write_text("#!/usr/bin/env bash\necho package shim\n", encoding="utf-8")
    shim.chmod(0o755)

    proc = subprocess.run(
        ["node", str(BIN), "init", "--dir", str(ROOT)],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{path_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "stack ready" in proc.stderr


def test_node_cli_preserves_install_cli_value_flags(tmp_path: Path) -> None:
    _require_node()
    stack = _fake_checkout(tmp_path)
    bin_dir = tmp_path / "custom-bin"

    subprocess.run(
        [
            "node",
            str(BIN),
            "install-cli",
            "--dir",
            str(stack),
            "--bin-dir",
            str(bin_dir),
            "--name",
            "custom",
            "--dry-run",
        ],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "install-cli",
        "--bin-dir",
        str(bin_dir),
        "--name",
        "custom",
        "--dry-run",
    ]


def test_node_cli_preserves_uninstall_cli_value_flags(tmp_path: Path) -> None:
    _require_node()
    stack = _fake_checkout(tmp_path)
    bin_dir = tmp_path / "custom-bin"

    subprocess.run(
        [
            "node",
            str(BIN),
            "uninstall-cli",
            "--dir",
            str(stack),
            "--bin-dir",
            str(bin_dir),
            "--name",
            "custom",
            "--dry-run",
        ],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "uninstall-cli",
        "--bin-dir",
        str(bin_dir),
        "--name",
        "custom",
        "--dry-run",
    ]


def test_node_cli_rejects_native_windows_before_checkout() -> None:
    _require_node()

    proc = subprocess.run(
        ["node", str(BIN), "doctor"],
        cwd="/tmp",
        env={**os.environ, "HEALTHSAVE_TEST_PLATFORM": "win32"},
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert proc.returncode == 1
    assert "WSL2" in proc.stderr
    assert "install.ps1" in proc.stderr


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


def test_node_cli_delegates_onboard_command(tmp_path: Path) -> None:
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
        ["node", str(BIN), "onboard", "--dir", str(stack)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "onboard",
    ]


def test_node_cli_delegates_uninstall_cli_command(tmp_path: Path) -> None:
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
        ["node", str(BIN), "uninstall-cli", "--dir", str(stack)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert (stack / "delegated-args.txt").read_text(encoding="utf-8").splitlines() == [
        "uninstall-cli",
    ]
