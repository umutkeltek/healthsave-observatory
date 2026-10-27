"""The bundled Mosquitto broker requires a login for new installs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "deploy" / "mosquitto" / "entrypoint.sh"


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run_entrypoint(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    runtime = tmp_path / "runtime"
    bin_dir.mkdir()
    runtime.mkdir()
    _fake(bin_dir, "mosquitto_passwd", f'printf "%s\\n" "$*" > "{tmp_path}/passwd-args"')
    _fake(bin_dir, "mosquitto", f'printf "%s\\n" "$*" > "{tmp_path}/mosquitto-args"')
    _fake(bin_dir, "chown", "exit 0")
    proc = subprocess.run(
        ["sh", str(ENTRYPOINT)],
        env={
            "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
            "MOSQUITTO_BASE_CONF": str(ROOT / "deploy" / "mosquitto" / "mosquitto.conf"),
            "MOSQUITTO_RUNTIME_DIR": str(runtime),
            **env,
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    return proc, runtime


def test_base_config_leaves_anonymous_access_to_the_entrypoint() -> None:
    conf = (ROOT / "deploy" / "mosquitto" / "mosquitto.conf").read_text(encoding="utf-8")
    assert not re.search(r"^\s*allow_anonymous", conf, re.M)
    assert not re.search(r"^\s*password_file", conf, re.M)


def test_entrypoint_requires_login_when_credentials_are_set(tmp_path: Path) -> None:
    proc, runtime = _run_entrypoint(
        tmp_path, MOSQUITTO_USERNAME="healthsave", MOSQUITTO_PASSWORD="s3cret"
    )
    assert proc.returncode == 0, proc.stderr
    conf = (runtime / "mosquitto.conf").read_text(encoding="utf-8")
    assert "allow_anonymous false" in conf
    assert f"password_file {runtime / 'mosquitto.passwd'}" in conf
    assert (tmp_path / "passwd-args").read_text().split() == [
        "-b",
        str(runtime / "mosquitto.passwd"),
        "healthsave",
        "s3cret",
    ]
    assert (tmp_path / "mosquitto-args").read_text().split() == [
        "-c",
        str(runtime / "mosquitto.conf"),
    ]
    assert "s3cret" not in proc.stdout + proc.stderr


def test_entrypoint_stays_anonymous_and_warns_without_credentials(tmp_path: Path) -> None:
    proc, runtime = _run_entrypoint(tmp_path)
    assert proc.returncode == 0, proc.stderr
    conf = (runtime / "mosquitto.conf").read_text(encoding="utf-8")
    assert "allow_anonymous true" in conf
    assert "password_file" not in conf
    assert "WARNING anonymous access" in proc.stderr
    assert not (tmp_path / "passwd-args").exists()


def test_compose_wires_broker_login_and_bridge_fallback() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./deploy/mosquitto/entrypoint.sh:/healthsave/entrypoint.sh:ro" in compose
    assert "MOSQUITTO_PASSWORD: ${MOSQUITTO_PASSWORD:-}" in compose
    assert "HA_MQTT_USERNAME: ${HA_MQTT_USERNAME:-${MOSQUITTO_USERNAME:-}}" in compose
    assert "HA_MQTT_PASSWORD: ${HA_MQTT_PASSWORD:-${MOSQUITTO_PASSWORD:-}}" in compose


def _checkout(tmp_path: Path, env_text: str | None) -> tuple[Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    checkout.mkdir()
    bin_dir.mkdir()
    for name in ("healthsave", "setup.sh", ".env.example", "config.yaml.example"):
        shutil.copy(ROOT / name, checkout / name)
    if env_text is not None:
        (checkout / ".env").write_text(env_text, encoding="utf-8")
    for name in ("docker", "curl"):
        (bin_dir / name).write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    return checkout, bin_dir


def _cli(checkout: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(checkout / "healthsave"), *args],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_basic_setup_generates_broker_login(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, None)
    proc = _cli(checkout, bin_dir, "setup", "basic", "--no-input")
    assert proc.returncode == 0, proc.stderr
    env = (checkout / ".env").read_text(encoding="utf-8")
    assert "\nMOSQUITTO_USERNAME=healthsave\n" in env
    assert re.search(r"^MOSQUITTO_PASSWORD=[0-9a-f]{32}$", env, re.M)


def test_up_home_assistant_prints_bundled_broker_login(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(
        tmp_path, "MOSQUITTO_USERNAME=healthsave\nMOSQUITTO_PASSWORD=abc123\n"
    )
    proc = _cli(checkout, bin_dir, "up", "--home-assistant")
    assert proc.returncode == 0, proc.stderr
    assert "Username: healthsave  Password: abc123" in proc.stdout


def test_up_home_assistant_warns_when_broker_is_anonymous(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, "HA_MQTT_BROKER=mqtt\n")
    proc = _cli(checkout, bin_dir, "up", "--home-assistant")
    assert proc.returncode == 0, proc.stderr
    assert "allows anonymous access" in proc.stdout + proc.stderr
