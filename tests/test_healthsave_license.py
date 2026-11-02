"""healthsave license activate / status, run through the real bash CLI.

The CLI checks licences with `python -m licensing`. HEALTHSAVE_PYTHON points it
at a shim that trusts a throwaway test key (see tests/licence_testkit.py); one
test uses the real embedded key to prove a test-signed file is refused.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.licence_testkit import ROOT, TestKey, expired, make_key, mint, python_shim

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "__LOG__"
exit 0
"""


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    checkout.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    for name in ("healthsave", "setup.sh"):
        shutil.copy(ROOT / name, checkout / name)
    shutil.copytree(ROOT / "packages" / "py" / "licensing", checkout / "packages/py/licensing")
    log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER.replace("__LOG__", str(log)), encoding="utf-8")
    docker.chmod(0o755)
    return checkout, bin_dir, log


def _cli(
    checkout: Path, bin_dir: Path, python: Path | str, *args: str, cwd: Path | str = "/tmp"
) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"}
    env.pop("HEALTHSAVE_LICENSE_FILE", None)
    env["HEALTHSAVE_PYTHON"] = str(python)
    return subprocess.run(
        [str(checkout / "healthsave"), *args],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=60,
    )


def _with_test_key(tmp_path: Path) -> tuple[Path, Path, Path, TestKey, Path]:
    checkout, bin_dir, log = _setup(tmp_path)
    key = make_key()
    return checkout, bin_dir, log, key, python_shim(bin_dir, key)


def test_status_without_a_licence_is_community_and_succeeds(tmp_path):
    checkout, bin_dir, _, _, shim = _with_test_key(tmp_path)
    proc = _cli(checkout, bin_dir, shim, "license", "status")
    assert proc.returncode == 0, proc.stderr
    assert "No licence installed" in proc.stdout
    assert "every free feature works" in proc.stdout


def test_activate_verifies_installs_privately_and_status_reads_it(tmp_path):
    checkout, bin_dir, log, key, shim = _with_test_key(tmp_path)
    licence = tmp_path / "download.license"
    licence.write_text(mint(key) + "\n")

    proc = _cli(checkout, bin_dir, shim, "license", "activate", str(licence))
    assert proc.returncode == 0, proc.stderr
    assert "Tier:      care" in proc.stdout
    assert "active until" in proc.stdout
    assert "Licence activated" in proc.stdout
    assert "nothing is sent anywhere" in proc.stdout
    installed = checkout / "healthsave.license"
    assert installed.read_text() == licence.read_text()
    assert installed.stat().st_mode & 0o777 == 0o600

    proc = _cli(checkout, bin_dir, shim, "license", "status")
    assert proc.returncode == 0, proc.stderr
    assert "care.backup.offsite" in proc.stdout
    assert not log.exists(), "a host Python check never needs docker"


def test_activate_resolves_a_relative_path_from_where_it_was_run(tmp_path):
    checkout, bin_dir, _, key, shim = _with_test_key(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "my.license").write_text(mint(key))
    proc = _cli(checkout, bin_dir, shim, "license", "activate", "my.license", cwd=downloads)
    assert proc.returncode == 0, proc.stderr
    assert (checkout / "healthsave.license").is_file()


def test_activate_refuses_a_tampered_file_and_keeps_the_old_licence(tmp_path):
    checkout, bin_dir, _, key, shim = _with_test_key(tmp_path)
    good = mint(key)
    (checkout / "healthsave.license").write_text(good)
    tampered = tmp_path / "tampered.license"
    tampered.write_text(good[:10] + ("A" if good[10] != "A" else "B") + good[11:])

    proc = _cli(checkout, bin_dir, shim, "license", "activate", str(tampered))
    assert proc.returncode == 1
    assert "Not activated" in proc.stderr
    assert (checkout / "healthsave.license").read_text() == good


def test_activate_refuses_a_licence_past_its_grace_period(tmp_path):
    checkout, bin_dir, _, key, shim = _with_test_key(tmp_path)
    old = tmp_path / "old.license"
    old.write_text(mint(key, **expired(days_ago=20)))
    proc = _cli(checkout, bin_dir, shim, "license", "activate", str(old))
    assert proc.returncode == 1
    assert "expired" in proc.stdout + proc.stderr
    assert not (checkout / "healthsave.license").exists()


def test_activate_accepts_a_licence_in_grace_and_says_so(tmp_path):
    checkout, bin_dir, _, key, shim = _with_test_key(tmp_path)
    late = tmp_path / "late.license"
    late.write_text(mint(key, **expired(days_ago=2)))
    proc = _cli(checkout, bin_dir, shim, "license", "activate", str(late))
    assert proc.returncode == 0, proc.stderr
    assert "in grace period" in proc.stdout


def test_status_of_an_expired_licence_fails(tmp_path):
    checkout, bin_dir, _, key, shim = _with_test_key(tmp_path)
    (checkout / "healthsave.license").write_text(mint(key, **expired(days_ago=40)))
    proc = _cli(checkout, bin_dir, shim, "license", "status")
    assert proc.returncode == 1
    assert "has expired" in proc.stderr


def test_the_real_embedded_key_refuses_a_test_signed_licence(tmp_path):
    checkout, bin_dir, _ = _setup(tmp_path)
    licence = tmp_path / "test.license"
    licence.write_text(mint(make_key()))
    proc = _cli(checkout, bin_dir, sys.executable, "license", "activate", str(licence))
    assert proc.returncode == 1
    assert "signature does not match" in proc.stderr
    assert not (checkout / "healthsave.license").exists()


def test_unknown_license_subcommand_is_a_usage_error(tmp_path):
    checkout, bin_dir, _, _, shim = _with_test_key(tmp_path)
    proc = _cli(checkout, bin_dir, shim, "license", "renew")
    assert proc.returncode == 2
    assert "Unknown license command" in proc.stderr
