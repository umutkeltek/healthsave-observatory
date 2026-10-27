"""The CLI mints an API key at setup and shows what the HealthSave app needs to pair."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "0123456789abcdef0123456789abcdef0123456789abcdef"


def _setup_helper(snippet: str) -> str:
    script = f"""
set -euo pipefail
export HEALTHSAVE_SETUP_TEST=1
source "{ROOT / "setup.sh"}"
{snippet}
"""
    return subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True).stdout


def _checkout(tmp_path: Path, env_text: str | None) -> tuple[Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    checkout.mkdir()
    bin_dir.mkdir()
    for name in ("healthsave", "setup.sh", ".env.example", "config.yaml.example"):
        shutil.copy(ROOT / name, checkout / name)
    if env_text is not None:
        (checkout / ".env").write_text(env_text, encoding="utf-8")
    return checkout, bin_dir


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(checkout: Path, bin_dir: Path, *args: str, stdin=subprocess.DEVNULL):
    # qrencode is hidden so output does not depend on the host machine.
    _fake(bin_dir, "qrencode", "exit 127")
    os.remove(bin_dir / "qrencode")
    return subprocess.run(
        [str(checkout / "healthsave"), *args],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        text=True,
        capture_output=True,
        timeout=20,
        stdin=stdin,
    )


def _env_value(checkout: Path, key: str) -> str:
    for line in (checkout / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def test_rand_api_key_is_48_hex_chars() -> None:
    first = _setup_helper("rand_api_key").strip()
    second = _setup_helper("rand_api_key").strip()
    assert re.fullmatch(r"[0-9a-f]{48}", first)
    assert first != second


def test_pairing_url_percent_encodes_server_url_and_key() -> None:
    url = _setup_helper('build_pairing_url "https://obs.example.com:8443/x?y=1" "a b&c"')
    assert url == (
        "healthsave://pair?url=https%3A%2F%2Fobs.example.com%3A8443%2Fx%3Fy%3D1&key=a%20b%26c"
    )


def test_pairing_url_without_key_omits_key_param() -> None:
    url = _setup_helper('build_pairing_url "http://192.168.1.5:8000" ""')
    assert url == "healthsave://pair?url=http%3A%2F%2F192.168.1.5%3A8000"


def test_pair_shows_url_and_key(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, f"API_KEY={KEY}\n")
    proc = _run(checkout, bin_dir, "pair", "--url", "https://obs.example.com")
    assert proc.returncode == 0, proc.stderr
    assert "Server URL:  https://obs.example.com" in proc.stdout
    assert f"API key:     {KEY}" in proc.stdout
    assert "No API key is set" not in proc.stdout + proc.stderr


def test_pair_warns_when_api_is_open(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, "API_KEY=\n")
    proc = _run(checkout, bin_dir, "pair", "--url", "http://10.0.0.2:8000")
    assert proc.returncode == 0, proc.stderr
    assert "No API key is set" in proc.stdout + proc.stderr
    assert "healthsave pair --new-key" in proc.stdout + proc.stderr


def test_pair_new_key_refuses_without_confirmation(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, f"API_KEY={KEY}\n")
    proc = _run(checkout, bin_dir, "pair", "--new-key")
    assert proc.returncode == 2
    assert "--yes" in proc.stderr
    assert _env_value(checkout, "API_KEY") == KEY


def test_pair_new_key_with_yes_rotates_key(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, f"API_KEY={KEY}\nWEB_BIND=127.0.0.1\n")
    _fake(bin_dir, "docker", "exit 1")  # daemon down: key is written, restart skipped
    proc = _run(checkout, bin_dir, "pair", "--new-key", "--yes", "--url", "http://h:8000")
    assert proc.returncode == 0, proc.stderr
    new_key = _env_value(checkout, "API_KEY")
    assert re.fullmatch(r"[0-9a-f]{48}", new_key)
    assert new_key != KEY
    assert f"API key:     {new_key}" in proc.stdout
    assert _env_value(checkout, "WEB_BIND") == "127.0.0.1"


def test_pair_requires_env_file(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, None)
    proc = _run(checkout, bin_dir, "pair")
    assert proc.returncode == 1
    assert "healthsave setup basic" in proc.stderr


def test_basic_setup_mints_api_key_and_prints_it(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, None)
    _fake(bin_dir, "docker", "exit 0")
    _fake(bin_dir, "curl", "exit 0")
    proc = _run(checkout, bin_dir, "setup", "basic", "--no-input")
    assert proc.returncode == 0, proc.stderr
    key = _env_value(checkout, "API_KEY")
    assert re.fullmatch(r"[0-9a-f]{48}", key)
    assert f"API key:     {key}" in proc.stdout


def test_basic_setup_keeps_existing_env_and_key(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, "API_KEY=\nDB_PASSWORD=x\n")
    _fake(bin_dir, "docker", "exit 0")
    _fake(bin_dir, "curl", "exit 0")
    proc = _run(checkout, bin_dir, "setup", "basic", "--no-input")
    assert proc.returncode == 0, proc.stderr
    # An existing install keeps its (empty) key: minting one silently would cut off paired phones.
    assert _env_value(checkout, "API_KEY") == ""
    assert "No API key is set" in proc.stdout + proc.stderr
