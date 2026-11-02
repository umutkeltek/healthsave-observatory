"""Care backups: --encrypt, --offsite, --schedule, gated on the licence.

Driven against a fake docker like test_healthsave_backup.py; encryption uses
the real openssl. Licences are signed by a throwaway key that the CLI trusts
through HEALTHSAVE_PYTHON (tests/licence_testkit.py).
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.licence_testkit import ROOT, expired, make_key, mint, python_shim

pytestmark = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl is required")

PASSPHRASE = "correct horse=battery/staple+"
CIPHER = ["-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-md", "sha256"]

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "__LOG__"
if [ "$1" = "info" ]; then exit 0; fi
case "$*" in
  *"ps --status running --services"*) printf 'db\napi\nweb\n' ;;
  *"pg_dump"*) printf 'PGDMP-fake-dump' ;;
  *"extversion"*) printf '2.17.2\n' ;;
  *"schema_migrations"*) printf '27\n' ;;
  *"pg_restore"*) cat > "__RESTORED__" ;;
esac
exit 0
"""

FAKE_RCLONE = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "__LOG__"
exit __RC__
"""

FAKE_CRONTAB = r"""#!/usr/bin/env bash
printf 'crontab %s\n' "$*" >> "__LOG__"
if [ "$1" = "-l" ]; then
  [ -f "__STATE__" ] && { cat "__STATE__"; exit 0; }
  echo "no crontab for test" >&2
  exit 1
fi
if [ "$1" = "-" ]; then cat > "__STATE__"; exit 0; fi
exit 0
"""

FAKE_LAUNCHCTL = r"""#!/usr/bin/env bash
printf 'launchctl %s\n' "$*" >> "__LOG__"
exit 0
"""


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.checkout = tmp_path / "checkout"
        self.bin = tmp_path / "bin"
        self.home = tmp_path / "home"
        self.log = tmp_path / "calls.log"
        for directory in (self.checkout, self.bin, self.home):
            directory.mkdir(parents=True)
        for name in ("healthsave", "setup.sh"):
            shutil.copy(ROOT / name, self.checkout / name)
        shutil.copytree(
            ROOT / "packages" / "py" / "licensing", self.checkout / "packages/py/licensing"
        )
        (self.checkout / ".env").write_text(
            f"API_KEY=k\nBACKUP_PASSPHRASE={PASSPHRASE}\n", encoding="utf-8"
        )
        (self.checkout / "config.yaml").write_text("analysis: {}\n", encoding="utf-8")
        self._tool(
            "docker",
            FAKE_DOCKER.replace("__RESTORED__", str(tmp_path / "restored.dump")),
        )
        self.key = make_key()
        self.shim = python_shim(self.bin, self.key)
        self.extra_env: dict[str, str] = {}

    def _tool(self, name: str, body: str) -> None:
        tool = self.bin / name
        tool.write_text(body.replace("__LOG__", str(self.log)), encoding="utf-8")
        tool.chmod(0o755)

    def license(self, **overrides) -> None:
        (self.checkout / "healthsave.license").write_text(mint(self.key, **overrides))

    def rclone(self, rc: int = 0) -> None:
        self._tool("rclone", FAKE_RCLONE.replace("__RC__", str(rc)))

    def crontab(self) -> Path:
        state = self.tmp / "crontab.state"
        self._tool("crontab", FAKE_CRONTAB.replace("__STATE__", str(state)))
        return state

    def launchctl(self) -> None:
        self._tool("launchctl", FAKE_LAUNCHCTL)

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "HOME": str(self.home),
            "HEALTHSAVE_PYTHON": str(self.shim),
            **self.extra_env,
        }
        for name in ("HEALTHSAVE_LICENSE_FILE", "BACKUP_PASSPHRASE", "HEALTHSAVE_SCHEDULER"):
            if name not in self.extra_env:
                env.pop(name, None)
        return subprocess.run(
            [str(self.checkout / "healthsave"), *args],
            cwd="/tmp",
            env=env,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=60,
        )

    def calls(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def backups(self, pattern: str = "healthsave-*") -> list[Path]:
        return sorted((self.checkout / "backups").glob(pattern))


def _decrypt(path: Path, out: Path, passphrase: str = PASSPHRASE) -> None:
    subprocess.run(
        ["openssl", "enc", "-d", *CIPHER, "-pass", "env:P", "-in", str(path), "-out", str(out)],
        env={**os.environ, "P": passphrase},
        check=True,
        capture_output=True,
    )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# --- gating -----------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("backup", "--encrypt"),
        ("backup", "--offsite", "b2:bucket/hs"),
        ("backup", "--schedule", "daily"),
    ],
)
def test_care_options_are_refused_without_a_licence_and_touch_nothing(env, args):
    env.rclone()
    proc = env.run(*args)
    assert proc.returncode == 1
    assert "part of Observatory Care" in proc.stderr
    assert "Everything free keeps working" in proc.stderr
    assert "pg_dump" not in env.calls()
    assert "rclone" not in env.calls()
    assert not (env.checkout / "backups").exists()


def test_plain_backup_stays_free(env):
    proc = env.run("backup")
    assert proc.returncode == 0, proc.stderr
    assert len(env.backups("healthsave-backup-*.tar")) == 1


def test_a_licence_without_the_backup_feature_is_refused(env):
    env.license(features=["care.restore.drill"])
    proc = env.run("backup", "--encrypt")
    assert proc.returncode == 1
    assert "does not include care.backup.offsite" in proc.stderr
    assert not (env.checkout / "backups").exists()


def test_a_licence_past_its_grace_period_is_refused(env):
    env.license(**expired(days_ago=15))
    proc = env.run("backup", "--encrypt")
    assert proc.returncode == 1
    assert "grace period ended" in proc.stderr
    assert "pg_dump" not in env.calls()


def test_a_licence_in_grace_still_works_and_warns(env):
    env.license(**expired(days_ago=5))
    proc = env.run("backup", "--encrypt")
    assert proc.returncode == 0, proc.stderr
    assert "keep working until" in proc.stderr


# --- --encrypt --------------------------------------------------------------


def test_encrypt_writes_only_ciphertext_that_openssl_can_open(env):
    env.license()
    proc = env.run("backup", "--encrypt")
    assert proc.returncode == 0, proc.stderr
    assert "Encrypted backup written" in proc.stdout

    [archive] = env.backups()
    assert archive.name.endswith(".tar.enc")
    assert archive.stat().st_mode & 0o777 == 0o600
    assert archive.read_bytes().startswith(b"Salted__")
    assert PASSPHRASE not in proc.stdout + proc.stderr + env.calls()

    plain = env.tmp / "plain.tar"
    _decrypt(archive, plain)
    with tarfile.open(plain) as tar:
        assert sorted(tar.getnames()) == ["MANIFEST", "config.yaml", "db.dump", "env"]
        manifest = tar.extractfile("MANIFEST").read().decode()
    assert "format=healthsave-backup-1" in manifest
    assert "db_sha256=" in manifest


def test_encrypt_needs_a_passphrase_and_says_how_to_set_one(env):
    env.license()
    (env.checkout / ".env").write_text("API_KEY=k\n", encoding="utf-8")
    proc = env.run("backup", "--encrypt")
    assert proc.returncode == 1
    assert "BACKUP_PASSPHRASE=" in proc.stderr
    assert "password manager" in proc.stderr
    assert "pg_dump" not in env.calls()


def test_quoted_passphrase_in_env_file_is_unquoted(env):
    env.license()
    (env.checkout / ".env").write_text(f'BACKUP_PASSPHRASE="{PASSPHRASE}"\n', encoding="utf-8")
    assert env.run("backup", "--encrypt").returncode == 0
    [archive] = env.backups()
    _decrypt(archive, env.tmp / "plain.tar")


# --- restore of encrypted backups (never gated) -----------------------------


def test_restore_decrypts_without_a_licence(env):
    env.license()
    assert env.run("backup", "--encrypt").returncode == 0
    [archive] = env.backups()
    (env.checkout / "healthsave.license").unlink()

    proc = env.run("restore", str(archive), "--yes")
    assert proc.returncode == 0, proc.stderr
    assert "Restored. 27 migrations" in proc.stdout
    assert (env.tmp / "restored.dump").read_bytes() == b"PGDMP-fake-dump"


def test_restore_takes_the_passphrase_from_the_environment(env):
    env.license()
    assert env.run("backup", "--encrypt").returncode == 0
    [archive] = env.backups()
    (env.checkout / ".env").write_text("API_KEY=k\n", encoding="utf-8")
    env.extra_env["BACKUP_PASSPHRASE"] = PASSPHRASE
    proc = env.run("restore", str(archive), "--yes")
    assert proc.returncode == 0, proc.stderr


def test_restore_with_the_wrong_passphrase_changes_nothing(env):
    env.license()
    assert env.run("backup", "--encrypt").returncode == 0
    [archive] = env.backups()
    (env.checkout / ".env").write_text("BACKUP_PASSPHRASE=wrong\n", encoding="utf-8")
    proc = env.run("restore", str(archive), "--yes")
    assert proc.returncode == 1
    assert "Could not decrypt" in proc.stderr
    assert "DROP DATABASE" not in env.calls()


def test_restore_refuses_a_dump_that_does_not_match_its_checksum(env):
    work = env.tmp / "forged"
    work.mkdir()
    (work / "MANIFEST").write_text(
        "format=healthsave-backup-1\ntimescaledb=2.17.2\nmigrations=27\ndb_sha256=" + "0" * 64
    )
    (work / "db.dump").write_bytes(b"PGDMP-other")
    forged = env.tmp / "forged.tar"
    with tarfile.open(forged, "w") as tar:
        tar.add(work / "MANIFEST", arcname="MANIFEST")
        tar.add(work / "db.dump", arcname="db.dump")
    proc = env.run("restore", str(forged), "--yes")
    assert proc.returncode == 1
    assert "damaged" in proc.stderr
    assert "DROP DATABASE" not in env.calls()


# --- --offsite --------------------------------------------------------------


def test_offsite_encrypts_and_copies_with_rclone(env):
    env.license()
    env.rclone()
    proc = env.run("backup", "--offsite", "b2:bucket/healthsave")
    assert proc.returncode == 0, proc.stderr
    [archive] = env.backups()
    assert archive.name.endswith(".tar.enc")
    assert f"copy backups/{archive.name} b2:bucket/healthsave" in env.calls()
    assert f"Copied off-site: b2:bucket/healthsave/{archive.name}" in proc.stdout


def test_offsite_without_rclone_fails_before_any_backup(env):
    env.license()
    proc = env.run("backup", "--offsite", "b2:bucket/healthsave")
    assert proc.returncode == 1
    assert "rclone" in proc.stderr
    assert "pg_dump" not in env.calls()


def test_offsite_copy_failure_keeps_the_local_file(env):
    env.license()
    env.rclone(rc=3)
    proc = env.run("backup", "--offsite", "b2:bucket/healthsave")
    assert proc.returncode == 1
    assert "local copy is kept" in proc.stderr
    assert len(env.backups("*.tar.enc")) == 1


# --- --schedule -------------------------------------------------------------


def test_schedule_prints_a_cron_line_without_installing(env):
    env.license()
    state = env.crontab()
    env.extra_env["HEALTHSAVE_SCHEDULER"] = "cron"
    proc = env.run("backup", "--schedule", "daily", "--out", "/mnt/nas/hs")
    assert proc.returncode == 0, proc.stderr
    line = proc.stdout.strip().splitlines()[-1]
    assert line.startswith("15 3 * * * cd ")
    assert "./healthsave 'backup' '--encrypt' '--out' '/mnt/nas/hs'" in line
    assert line.endswith("# healthsave-scheduled-backup")
    assert "crontab" not in env.calls()
    assert not state.exists()


def test_schedule_yes_installs_one_cron_job_and_off_removes_it(env):
    env.license()
    env.rclone()
    state = env.crontab()
    state.write_text("0 1 * * * echo keep-me\n")
    env.extra_env["HEALTHSAVE_SCHEDULER"] = "cron"

    for _ in range(2):
        proc = env.run("backup", "--schedule", "weekly", "--offsite", "b2:x/y", "--yes")
        assert proc.returncode == 0, proc.stderr
    lines = state.read_text().splitlines()
    assert lines[0] == "0 1 * * * echo keep-me"
    [job] = [line for line in lines if "healthsave-scheduled-backup" in line]
    assert job.startswith("15 3 * * 0 ")
    assert "'--offsite' 'b2:x/y'" in job
    assert (env.checkout / "backups").is_dir()

    # Removing never needs a licence: a lapsed licence must not trap the job.
    (env.checkout / "healthsave.license").unlink()
    proc = env.run("backup", "--schedule", "off")
    assert proc.returncode == 0, proc.stderr
    assert state.read_text().splitlines() == ["0 1 * * * echo keep-me"]


def test_scheduled_cron_command_runs_as_shell(env):
    # The printed line must be valid sh: run its command part with a stub CLI.
    env.license()
    env.extra_env["HEALTHSAVE_SCHEDULER"] = "cron"
    proc = env.run("backup", "--schedule", "daily", "--offsite", "it's:a path")
    assert proc.returncode == 1  # rclone missing
    env.rclone()
    proc = env.run("backup", "--schedule", "daily", "--offsite", "it's:a path")
    assert proc.returncode == 0, proc.stderr
    line = proc.stdout.strip().splitlines()[-1]
    command = line.split(" ", 5)[5].rsplit(" # ", 1)[0]
    stub_dir = env.tmp / "stub"
    stub_dir.mkdir()
    shutil.copytree(env.checkout, stub_dir / "co")
    stub = stub_dir / "co" / "healthsave"
    stub.write_text('#!/bin/sh\nprintf "%s|" "$@" > args.out\n')
    command = command.replace(str(env.checkout), str(stub_dir / "co"))
    subprocess.run(["/bin/sh", "-c", command], check=True)
    assert (stub_dir / "co" / "args.out").read_text() == ("backup|--encrypt|--offsite|it's:a path|")


def test_schedule_with_launchd_writes_a_valid_plist(env):
    env.license()
    env.launchctl()
    env.extra_env["HEALTHSAVE_SCHEDULER"] = "launchd"
    plist_path = env.home / "Library/LaunchAgents/com.healthsave.observatory.backup.plist"

    proc = env.run("backup", "--schedule", "weekly")
    assert proc.returncode == 0, proc.stderr
    assert "<key>ProgramArguments</key>" in proc.stdout
    assert not plist_path.exists()

    proc = env.run("backup", "--schedule", "weekly", "--yes")
    assert proc.returncode == 0, proc.stderr
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["Label"] == "com.healthsave.observatory.backup"
    assert plist["ProgramArguments"] == [
        str(env.checkout / "healthsave"),
        "backup",
        "--encrypt",
    ]
    assert plist["WorkingDirectory"] == str(env.checkout)
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 15, "Weekday": 0}
    assert "launchctl bootstrap gui/" in env.calls()

    (env.checkout / "healthsave.license").unlink()
    proc = env.run("backup", "--schedule", "off")
    assert proc.returncode == 0, proc.stderr
    assert not plist_path.exists()


def test_schedule_needs_the_passphrase_now(env):
    env.license()
    env.extra_env["HEALTHSAVE_SCHEDULER"] = "cron"
    (env.checkout / ".env").write_text("API_KEY=k\n", encoding="utf-8")
    proc = env.run("backup", "--schedule", "daily")
    assert proc.returncode == 1
    assert "BACKUP_PASSPHRASE" in proc.stderr


@pytest.mark.parametrize("args", [("--schedule", "hourly"), ("--yes",), ("--offsite",)])
def test_bad_backup_arguments_are_usage_errors(env, args):
    proc = env.run("backup", *args)
    assert proc.returncode == 2
