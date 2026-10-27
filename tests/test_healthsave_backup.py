"""healthsave backup / restore, driven against a fake docker.

The real round trip (backup -> change data -> restore -> rows and checksum match,
hypertables intact, pre-restore undo) was run against timescale/timescaledb
2.17.2-pg16; these tests pin the CLI flow so it stays that way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Records every call; answers like a running stack with TimescaleDB __TS__.
printf '%s\n' "$*" >> "__LOG__"
if [ "$1" = "info" ]; then exit 0; fi
args="$*"
case "$args" in
  *"ps --status running --services"*) printf 'db\napi\nweb\n' ;;
  *"pg_dump"*) printf 'PGDMP-fake-dump' ;;
  *"extversion"*) printf '__TS__\n' ;;
  *"schema_migrations"*) printf '27\n' ;;
  *"pg_restore"*) cat > "__RESTORED__" ;;
esac
exit 0
"""


def _setup(tmp_path: Path, timescale: str = "2.17.2") -> tuple[Path, Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    checkout.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    for name in ("healthsave", "setup.sh"):
        shutil.copy(ROOT / name, checkout / name)
    (checkout / ".env").write_text("API_KEY=k\nDB_PASSWORD=p\n", encoding="utf-8")
    (checkout / "config.yaml").write_text("analysis: {}\n", encoding="utf-8")
    log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        FAKE_DOCKER.replace("__LOG__", str(log))
        .replace("__TS__", timescale)
        .replace("__RESTORED__", str(tmp_path / "restored.dump")),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return checkout, bin_dir, log


def _cli(checkout: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(checkout / "healthsave"), *args],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
    )


def _backups(checkout: Path, label: str) -> list[Path]:
    return sorted((checkout / "backups").glob(f"healthsave-{label}-*.tar"))


def test_backup_writes_private_archive_with_manifest(tmp_path: Path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path)
    proc = _cli(checkout, bin_dir, "backup")
    assert proc.returncode == 0, proc.stderr

    [archive] = _backups(checkout, "backup")
    assert archive.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive) as tar:
        assert sorted(tar.getnames()) == ["MANIFEST", "config.yaml", "db.dump", "env"]
        manifest = tar.extractfile("MANIFEST").read().decode()
        assert tar.extractfile("db.dump").read() == b"PGDMP-fake-dump"
    assert "format=healthsave-backup-1" in manifest
    assert "timescaledb=2.17.2" in manifest
    assert "migrations=27" in manifest
    assert "unencrypted" in proc.stderr + proc.stdout


def test_backup_out_dir(tmp_path: Path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path)
    out = tmp_path / "nas"
    proc = _cli(checkout, bin_dir, "backup", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert len(list(out.glob("healthsave-backup-*.tar"))) == 1


def test_restore_requires_confirmation_and_changes_nothing(tmp_path: Path) -> None:
    checkout, bin_dir, log = _setup(tmp_path)
    assert _cli(checkout, bin_dir, "backup").returncode == 0
    [archive] = _backups(checkout, "backup")

    proc = _cli(checkout, bin_dir, "restore", str(archive))
    assert proc.returncode == 2
    assert "--yes" in proc.stderr
    assert "DROP DATABASE" not in log.read_text()


def test_restore_takes_safety_backup_then_restores_and_restarts(tmp_path: Path) -> None:
    checkout, bin_dir, log = _setup(tmp_path)
    assert _cli(checkout, bin_dir, "backup").returncode == 0
    [archive] = _backups(checkout, "backup")

    proc = _cli(checkout, bin_dir, "restore", str(archive), "--yes")
    assert proc.returncode == 0, proc.stderr
    assert "Restored. 27 migrations" in proc.stdout + proc.stderr
    assert len(_backups(checkout, "pre-restore")) == 1
    assert (tmp_path / "restored.dump").read_bytes() == b"PGDMP-fake-dump"

    calls = log.read_text().splitlines()

    def index(fragment: str) -> int:
        return next(i for i, call in enumerate(calls) if fragment in call)

    # Safety backup first, then stop clients, rebuild, restore, start them again.
    assert index("pg_dump") < index("compose stop api web")
    assert index("compose stop api web") < index("DROP DATABASE IF EXISTS healthsave WITH (FORCE)")
    assert index("DROP DATABASE") < index("timescaledb_pre_restore") < index("pg_restore")
    assert index("pg_restore") < index("timescaledb_post_restore") < index("compose start api web")


def test_restore_refuses_a_different_timescaledb_version(tmp_path: Path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path, timescale="2.17.2")
    assert _cli(checkout, bin_dir, "backup").returncode == 0
    [archive] = _backups(checkout, "backup")

    other_checkout, other_bin, other_log = _setup(tmp_path / "other", timescale="2.18.0")
    proc = _cli(other_checkout, other_bin, "restore", str(archive), "--yes")
    assert proc.returncode == 1
    assert "TimescaleDB 2.17.2" in proc.stderr
    assert "DROP DATABASE" not in other_log.read_text()


def test_restore_rejects_files_that_are_not_backups(tmp_path: Path) -> None:
    checkout, bin_dir, log = _setup(tmp_path)
    bogus = tmp_path / "bogus.tar"
    with tarfile.open(bogus, "w") as tar:
        tar.add(checkout / "config.yaml", arcname="config.yaml")
    proc = _cli(checkout, bin_dir, "restore", str(bogus), "--yes")
    assert proc.returncode == 1
    assert "not a healthsave backup" in proc.stderr
    assert not log.exists() or "DROP DATABASE" not in log.read_text()


def test_web_password_reset_deletes_the_settings_file_in_the_running_web_container(
    tmp_path: Path,
) -> None:
    checkout, bin_dir, log = _setup(tmp_path)
    (checkout / ".env").write_text("WEB_PASSWORD=fromenv\n", encoding="utf-8")
    proc = _cli(checkout, bin_dir, "web-password", "reset")
    assert proc.returncode == 0, proc.stderr
    assert "compose exec -T web rm -f /app/data/web-auth.json" in log.read_text()
    assert "Observatory web sign-in password: fromenv" in proc.stdout
