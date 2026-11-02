"""healthsave restore --drill (Care) and the row counts a backup records.

A fake docker plays both the live stack (docker compose exec -T db ...) and the
throwaway drill container (docker run / docker exec <name>). The real round
trip against timescale/timescaledb was run by hand; these tests pin the flow:
licence gate, counts compared, PASS/FAIL, container always removed, and no
call ever reaches the live database during a drill.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from tests.licence_testkit import ROOT, make_key, mint, python_shim

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "__DIR__/calls.log"
dir="__DIR__"
case "$*" in
  info*) exit 0 ;;
  *"ps --status running --services"*) printf 'db\napi\nweb\n' ;;
  "compose exec -T db pg_dump"*) printf 'PGDMP-fake-dump' ;;
  "compose exec"*"query_to_xml"*)
    n=$(cat "$dir/count-calls" 2>/dev/null || echo 0)
    n=$((n + 1))
    echo "$n" > "$dir/count-calls"
    counts="$dir/live-counts-$n"
    [ -f "$counts" ] || counts="$dir/live-counts"
    cat "$counts" ;;
  "compose exec"*"extversion"*) printf '2.17.2\n' ;;
  "compose exec"*"schema_migrations"*) printf '27\n' ;;
  "run -d"*) printf 'cid\n' ;;
  "exec "*"pg_isready"*)
    while [ -f "$dir/hang" ]; do sleep 0.2; done
    exit 0 ;;
  "exec "*"CREATE EXTENSION"*) exit "$(cat "$dir/extension-rc" 2>/dev/null || echo 0)" ;;
  "exec -i "*"pg_restore"*) cat > "$dir/drill-restored.dump" ;;
  "exec "*"query_to_xml"*) cat "$dir/drill-counts" ;;
  "exec "*"schema_migrations"*) cat "$dir/drill-migrations" 2>/dev/null || printf '27\n' ;;
esac
exit 0
"""

LIVE_COUNTS = "public.heart_rate=120\npublic.schema_migrations=27\npublic.sleep=7\n"


class Drill:
    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path
        self.checkout = tmp_path / "checkout"
        self.bin = tmp_path / "bin"
        self.checkout.mkdir()
        self.bin.mkdir()
        for name in ("healthsave", "setup.sh", "docker-compose.yml"):
            shutil.copy(ROOT / name, self.checkout / name)
        shutil.copytree(
            ROOT / "packages" / "py" / "licensing", self.checkout / "packages/py/licensing"
        )
        (self.checkout / ".env").write_text(
            "API_KEY=k\nBACKUP_PASSPHRASE=drill-pass\n", encoding="utf-8"
        )
        docker = self.bin / "docker"
        docker.write_text(FAKE_DOCKER.replace("__DIR__", str(tmp_path)), encoding="utf-8")
        docker.chmod(0o755)
        (tmp_path / "live-counts").write_text(LIVE_COUNTS)
        (tmp_path / "drill-counts").write_text(LIVE_COUNTS)
        self.key = make_key()
        self.shim = python_shim(self.bin, self.key)

    def license(self, **overrides) -> None:
        (self.checkout / "healthsave.license").write_text(mint(self.key, **overrides))

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "HEALTHSAVE_PYTHON": str(self.shim),
        }
        for name in ("HEALTHSAVE_LICENSE_FILE", "BACKUP_PASSPHRASE"):
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

    def calls(self) -> list[str]:
        log = self.dir / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def backup(self, *args: str) -> Path:
        proc = self.run("backup", *args)
        assert proc.returncode == 0, proc.stderr
        [archive] = sorted((self.checkout / "backups").glob("healthsave-backup-*"))
        return archive


def _manifest(archive: Path) -> str:
    with tarfile.open(archive) as tar:
        return tar.extractfile("MANIFEST").read().decode()


@pytest.fixture
def drill(tmp_path: Path) -> Drill:
    return Drill(tmp_path)


# --- the counts a backup records ---------------------------------------------


def test_backup_records_each_tables_row_count(drill):
    manifest = _manifest(drill.backup())
    assert "rows.public.heart_rate=120\n" in manifest
    assert "rows.public.sleep=7\n" in manifest
    calls = drill.calls()
    counts = [i for i, c in enumerate(calls) if "query_to_xml" in c]
    dump = next(i for i, c in enumerate(calls) if "pg_dump" in c)
    assert counts[0] < dump < counts[1], "counted before and after the dump"


def test_a_table_that_changed_during_the_dump_records_a_range(drill):
    (drill.dir / "live-counts-1").write_text("public.heart_rate=120\npublic.sleep=7\n")
    (drill.dir / "live-counts-2").write_text("public.heart_rate=125\npublic.sleep=7\n")
    manifest = _manifest(drill.backup())
    assert "rows.public.heart_rate=120..125\n" in manifest
    assert "rows.public.sleep=7\n" in manifest


# --- the drill ---------------------------------------------------------------


def test_drill_needs_a_licence(drill):
    archive = drill.backup()
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 1
    assert "part of Observatory Care" in proc.stderr
    assert not any(c.startswith("run ") for c in drill.calls())


def test_drill_passes_and_never_touches_the_live_database(drill):
    archive = drill.backup()
    drill.license()
    before = len(drill.calls())
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS - 3 tables and 154 rows restored" in proc.stdout
    assert "27 migrations" in proc.stdout
    assert (drill.dir / "drill-restored.dump").read_bytes() == b"PGDMP-fake-dump"

    calls = drill.calls()[before:]
    assert not [c for c in calls if c.startswith("compose")], "a drill never uses the stack"
    [run] = [c for c in calls if c.startswith("run ")]
    assert "--network none" in run
    assert "timescale/timescaledb:2.17.2-pg16" in run
    assert "timescaledb.telemetry_level=off" in run
    name = run.split("--name ")[1].split()[0]
    assert name.startswith("healthsave-drill-")
    assert calls[-1] == f"rm -f -v {name}", "container and its data volume are removed"
    assert any("CREATE EXTENSION timescaledb VERSION '2.17.2'" in c for c in calls)


def test_drill_reports_a_mismatch_as_fail_and_still_cleans_up(drill):
    archive = drill.backup()
    drill.license()
    (drill.dir / "drill-counts").write_text("public.heart_rate=119\npublic.schema_migrations=27\n")
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 1
    assert "MISMATCH" in proc.stdout
    assert "MISSING" in proc.stdout  # public.sleep never came back
    assert "RESULT: FAIL - 2 of 3 tables do not match" in proc.stdout
    assert drill.calls()[-1].startswith("rm -f -v healthsave-drill-")


def test_drill_accepts_a_count_inside_a_recorded_range(drill):
    (drill.dir / "live-counts-1").write_text("public.heart_rate=120\n")
    (drill.dir / "live-counts-2").write_text("public.heart_rate=125\n")
    archive = drill.backup()
    drill.license()
    (drill.dir / "drill-counts").write_text("public.heart_rate=123\n")
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 0, proc.stdout
    assert "120..125" in proc.stdout


def test_drill_fails_on_a_migrations_mismatch(drill):
    archive = drill.backup()
    drill.license()
    (drill.dir / "drill-migrations").write_text("26\n")
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 1
    assert "schema_migrations: expected 27, found 26" in proc.stdout


def test_drill_of_an_encrypted_backup(drill):
    drill.license()
    archive = drill.backup("--encrypt")
    assert archive.name.endswith(".tar.enc")
    proc = drill.run("restore", "--drill", str(archive))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout


def test_drill_of_a_backup_without_row_counts_fails_without_starting_a_container(drill):
    work = drill.dir / "old"
    work.mkdir()
    (work / "MANIFEST").write_text(
        "format=healthsave-backup-1\ntimescaledb=2.17.2\nmigrations=27\n"
    )
    (work / "db.dump").write_bytes(b"PGDMP-old")
    old = drill.dir / "old.tar"
    with tarfile.open(old, "w") as tar:
        tar.add(work / "MANIFEST", arcname="MANIFEST")
        tar.add(work / "db.dump", arcname="db.dump")
    drill.license()
    proc = drill.run("restore", "--drill", str(old))
    assert proc.returncode == 1
    assert "records no row counts" in proc.stdout
    assert not any(c.startswith("run ") for c in drill.calls())


def test_drill_cleans_up_when_the_image_lacks_the_timescaledb_version(drill):
    archive = drill.backup()
    drill.license()
    (drill.dir / "extension-rc").write_text("1")
    proc = drill.run("restore", "--drill", str(archive), "--image", "timescale/timescaledb:9-pg9")
    assert proc.returncode == 1
    assert "cannot run TimescaleDB 2.17.2" in proc.stdout
    assert "timescale/timescaledb:9-pg9" in next(c for c in drill.calls() if c.startswith("run "))
    assert drill.calls()[-1].startswith("rm -f -v healthsave-drill-")


def test_drill_uses_timescale_image_from_env(drill):
    archive = drill.backup()
    drill.license()
    with (drill.checkout / ".env").open("a") as env:
        env.write("TIMESCALE_IMAGE=timescale/timescaledb:2.17.2-pg17\n")
    assert drill.run("restore", "--drill", str(archive)).returncode == 0
    run = next(c for c in drill.calls() if c.startswith("run "))
    assert "timescale/timescaledb:2.17.2-pg17" in run


def test_image_without_drill_is_a_usage_error(drill):
    archive = drill.backup()
    proc = drill.run("restore", str(archive), "--image", "x")
    assert proc.returncode == 2


def test_interrupting_a_drill_still_removes_the_container(drill):
    archive = drill.backup()
    drill.license()
    (drill.dir / "hang").write_text("")
    env = {
        **os.environ,
        "PATH": f"{drill.bin}{os.pathsep}/usr/bin:/bin",
        "HEALTHSAVE_PYTHON": str(drill.shim),
    }
    proc = subprocess.Popen(
        [str(drill.checkout / "healthsave"), "restore", "--drill", str(archive)],
        cwd="/tmp",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + 30
    while not any("pg_isready" in c for c in drill.calls()):
        assert time.monotonic() < deadline, "the drill never started its container"
        time.sleep(0.1)
    os.killpg(proc.pid, signal.SIGINT)  # what Ctrl-C does
    proc.communicate(timeout=30)
    (drill.dir / "hang").unlink()
    assert proc.returncode != 0
    assert drill.calls()[-1].startswith("rm -f -v healthsave-drill-")
