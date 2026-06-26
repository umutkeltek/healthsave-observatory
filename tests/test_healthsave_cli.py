from __future__ import annotations

import json
import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "healthsave"


def _read_until(master_fd: int, needle: str, timeout: float = 2.0) -> tuple[str, bool]:
    deadline = time.monotonic() + timeout
    output = b""
    needle_bytes = needle.encode()

    while time.monotonic() < deadline:
        readable, _, _ = select.select([master_fd], [], [], 0.05)
        if not readable:
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if needle_bytes in output:
            return output.decode(errors="replace"), True

    return output.decode(errors="replace"), needle_bytes in output


def test_healthsave_help_works_from_other_directory() -> None:
    proc = subprocess.run(
        [str(CLI), "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert "Run from this checkout with ./healthsave" in proc.stdout
    assert "Usage:\n  healthsave <command>" in proc.stdout
    assert "setup" in proc.stdout
    assert "onboard" in proc.stdout
    assert "doctor" in proc.stdout
    assert "verify" in proc.stdout
    assert "version" in proc.stdout
    assert "uninstall-cli" in proc.stdout


def test_healthsave_doctor_help_does_not_run_checks() -> None:
    proc = subprocess.run(
        [str(CLI), "doctor", "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert "HealthSave doctor" in proc.stdout
    assert "Usage:" in proc.stdout
    assert "HealthSave Observatory doctor" not in proc.stdout


def test_healthsave_version_command() -> None:
    proc = subprocess.run(
        [str(CLI), "version"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert proc.stdout.strip() == "healthsave 0.3.0"


def test_healthsave_bare_command_opens_interactive_menu() -> None:
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        [str(CLI)],
        cwd="/tmp",
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output, visible = _read_until(master_fd, "Enter select", timeout=2.0)
        assert visible, f"menu was not visible; output={output!r}"
        assert "Setup HealthSave Observatory" in output
        assert "Control stack and optional layers" in output
        assert "Diagnose and verify" in output
        assert "Enter select" in output

        os.write(master_fd, b"\x1b[B\r")
        output, visible = _read_until(master_fd, "Start with optional layers", timeout=2.0)
        assert visible, f"stack submenu was not visible; output={output!r}"
        assert "Start with optional layers" in output
        output, visible = _read_until(master_fd, "Enter select", timeout=2.0)
        assert visible, f"stack submenu footer was not visible; output={output!r}"
        os.write(master_fd, b"q")
        output, visible = _read_until(master_fd, "Control Center", timeout=2.0)
        assert visible, f"menu did not return after q; output={output!r}"
        output, visible = _read_until(master_fd, "Enter select", timeout=2.0)
        assert visible, f"menu did not return after q; output={output!r}"
        os.write(master_fd, b"q")
        proc.wait(timeout=2)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.terminate()
        os.close(master_fd)


def test_healthsave_onboard_command_opens_interactive_menu() -> None:
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        [str(CLI), "onboard"],
        cwd="/tmp",
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
    )
    os.close(slave_fd)
    try:
        output, visible = _read_until(master_fd, "Enter select", timeout=2.0)
        assert visible, f"menu was not visible; output={output!r}"
        assert "Setup HealthSave Observatory" in output
        os.write(master_fd, b"q")
        proc.wait(timeout=2)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.terminate()
        os.close(master_fd)


def test_healthsave_setup_help_explains_basic_and_advanced() -> None:
    proc = subprocess.run(
        [str(CLI), "setup", "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert "healthsave setup basic" in proc.stdout
    assert "healthsave setup advanced" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--no-input" in proc.stdout


def test_healthsave_verify_help_does_not_run_verification() -> None:
    proc = subprocess.run(
        [str(CLI), "verify", "--help"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert "HealthSave verify" in proc.stdout
    assert "Docker E2E stack" in proc.stdout
    assert "make verify-local" not in proc.stdout


def test_healthsave_basic_setup_dry_run_is_non_mutating() -> None:
    proc = subprocess.run(
        [str(CLI), "setup", "basic", "--dry-run", "--no-input"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )

    assert "DRY RUN" in proc.stdout
    assert "Basic setup" in proc.stdout
    assert "Start default layers" in proc.stdout


def test_healthsave_advanced_setup_requires_tty_unless_dry_run() -> None:
    proc = subprocess.run(
        [str(CLI), "setup", "advanced"],
        cwd="/tmp",
        text=True,
        input="",
        capture_output=True,
        timeout=15,
    )

    assert proc.returncode == 2
    assert "Advanced setup needs an interactive terminal" in proc.stderr


def test_healthsave_json_doctor_is_machine_readable() -> None:
    proc = subprocess.run(
        [str(CLI), "--json", "doctor"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=25,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] in {True, False}
    assert proc.returncode == (0 if payload["ok"] else 1)
    assert payload["script_dir"] == str(ROOT)
    assert payload["platform"]["id"]
    assert isinstance(payload["tools"]["docker_cli"], bool)
    assert isinstance(payload["tools"]["docker_daemon"], bool)
    assert isinstance(payload["tools"]["docker_compose"], bool)
    assert isinstance(payload["config"]["env_file"], bool)
    assert isinstance(payload["config"]["config_file"], bool)
    assert payload["layers"]["api"]["service"] == "api"
    assert payload["layers"]["web"]["url"] == "http://localhost:4173"


def test_healthsave_layers_json_documents_product_layers() -> None:
    proc = subprocess.run(
        [str(CLI), "--json", "layers"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["layers"]["database"]["service"] == "db"
    assert payload["layers"]["api"]["required"] is True
    assert payload["layers"]["worker"]["service"] == "worker"
    assert payload["layers"]["web"]["description"] == "Primary insight-first web surface"
    assert payload["layers"]["grafana"]["service"] == "grafana"
    assert payload["layers"]["local_ai"]["profile"] == "local-ai"
    assert payload["layers"]["agents"]["service"] == "agents"


def test_healthsave_status_json_is_layer_aware() -> None:
    proc = subprocess.run(
        [str(CLI), "status", "--json"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=25,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["layers"]["database"]["service"] == "db"
    assert payload["layers"]["api"]["url"] == "http://localhost:8000"
    assert payload["layers"]["web"]["service"] == "web"
    assert payload["layers"]["grafana"]["required"] is True


def test_healthsave_install_cli_dry_run_is_discoverable() -> None:
    proc = subprocess.run(
        [str(CLI), "install-cli", "--dry-run"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Would install wrapper" in proc.stdout
    assert "Wrapper would execute" in proc.stdout
    assert str(CLI) in proc.stdout


def test_healthsave_install_and_uninstall_cli_wrapper(tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(CLI), "install-cli", "--bin-dir", str(tmp_path), "--name", "healthsave-test"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    wrapper = tmp_path / "healthsave-test"
    assert "Installed healthsave-test" in proc.stdout
    assert wrapper.exists()
    assert str(CLI) in wrapper.read_text(encoding="utf-8")

    proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path), "--name", "healthsave-test"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Removed" in proc.stdout
    assert not wrapper.exists()


def test_healthsave_install_cli_upgrades_legacy_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "healthsave"
    wrapper.write_text(
        f'#!/usr/bin/env bash\nexec "{ROOT}/healthsave" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "install-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Installed healthsave" in proc.stdout
    text = wrapper.read_text(encoding="utf-8")
    assert "# healthsave-wrapper:" in text


def test_healthsave_uninstall_cli_accepts_legacy_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "healthsave"
    wrapper.write_text(
        f'#!/usr/bin/env bash\nexec "{ROOT}/healthsave" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert "Removed" in proc.stdout
    assert not wrapper.exists()


def test_healthsave_install_cli_shell_escapes_checkout_path(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout $(touch pwned)"
    bin_dir = tmp_path / "bin"
    checkout.mkdir()
    bin_dir.mkdir()
    shutil.copy(ROOT / "healthsave", checkout / "healthsave")
    shutil.copy(ROOT / "setup.sh", checkout / "setup.sh")

    subprocess.run(
        [
            str(checkout / "healthsave"),
            "install-cli",
            "--bin-dir",
            str(bin_dir),
            "--name",
            "healthsave-escaped",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    subprocess.run(
        [str(bin_dir / "healthsave-escaped"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    assert not (tmp_path / "pwned").exists()


def test_healthsave_uninstall_cli_refuses_unrelated_file(tmp_path: Path) -> None:
    wrapper = tmp_path / "healthsave"
    wrapper.write_text("#!/usr/bin/env bash\necho unrelated\n", encoding="utf-8")
    wrapper.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert proc.returncode == 1
    assert "does not look like" in proc.stderr
    assert wrapper.exists()


def test_healthsave_install_cli_ignores_same_name_elsewhere_on_path(tmp_path: Path) -> None:
    path_bin = tmp_path / "path-bin"
    target_bin = tmp_path / "target-bin"
    path_bin.mkdir()
    target_bin.mkdir()
    existing = path_bin / "healthsave"
    existing.write_text("#!/usr/bin/env bash\necho npm shim\n", encoding="utf-8")
    existing.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "install-cli", "--bin-dir", str(target_bin), "--name", "healthsave"],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{path_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    wrapper = target_bin / "healthsave"
    assert "Installed healthsave" in proc.stdout
    assert wrapper.exists()
    assert str(CLI) in wrapper.read_text(encoding="utf-8")


def test_healthsave_uninstall_cli_requires_exact_wrapper_marker(tmp_path: Path) -> None:
    wrapper = tmp_path / "healthsave"
    wrapper.write_text(
        f"#!/usr/bin/env bash\n# mentions {CLI} but is not generated\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert proc.returncode == 1
    assert "wrapper created by" in proc.stderr
    assert wrapper.exists()


def test_healthsave_uninstall_cli_dry_run_requires_exact_wrapper_marker(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "healthsave"
    wrapper.write_text(
        f"#!/usr/bin/env bash\n# mentions {CLI} but is not generated\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path), "--dry-run"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert proc.returncode == 1
    assert "Would remove" not in proc.stdout
    assert "wrapper created by" in proc.stderr
    assert wrapper.exists()


def test_healthsave_install_cli_rejects_path_command_name(tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(CLI), "install-cli", "--bin-dir", str(tmp_path), "--name", "../healthsave"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert proc.returncode == 2
    assert "simple executable name" in proc.stderr


def test_healthsave_wrapper_commands_reject_symlinks_without_force(tmp_path: Path) -> None:
    target = tmp_path / "healthsave"
    target.symlink_to(tmp_path / "elsewhere")

    install_proc = subprocess.run(
        [str(CLI), "install-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )
    uninstall_proc = subprocess.run(
        [str(CLI), "uninstall-cli", "--bin-dir", str(tmp_path)],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert install_proc.returncode == 1
    assert "symlink" in install_proc.stderr
    assert uninstall_proc.returncode == 1
    assert "symlink" in uninstall_proc.stderr


def test_healthsave_home_assistant_external_broker_skips_bundled_mosquitto(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "docker-args.txt"
    checkout.mkdir()
    bin_dir.mkdir()
    shutil.copy(ROOT / "healthsave", checkout / "healthsave")
    shutil.copy(ROOT / "setup.sh", checkout / "setup.sh")
    (checkout / ".env").write_text(
        "HA_MQTT_ENABLED=false\nHA_MQTT_BROKER=mqtt\n",
        encoding="utf-8",
    )
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "info" ]; then exit 0; fi\n'
        f"printf '%s\\n' \"$*\" >> {calls}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)

    proc = subprocess.run(
        [str(checkout / "healthsave"), "up", "--home-assistant"],
        cwd="/tmp",
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HA_MQTT_BROKER": "mqtt.home.arpa",
        },
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    args = calls.read_text(encoding="utf-8")
    assert "--profile home-assistant" in args
    assert "--profile mosquitto" not in args
    assert "Including bundled MQTT broker" not in proc.stdout


def test_healthsave_unknown_command_exits_with_help() -> None:
    proc = subprocess.run(
        [str(CLI), "wat"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=2,
    )

    assert proc.returncode == 2
    assert "Unknown command: wat" in proc.stderr
    assert "Usage:\n  healthsave <command>" in proc.stdout
