"""healthsave update moves a git checkout to the newest release tag.

Uses a real local "origin" repository with release tags and a fake docker that
records calls, so no network or containers are involved.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git is required")

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "__LOG__"
if [ "$1" = "info" ]; then exit 0; fi
case "$*" in
  *"ps --status running --services"*) printf '__RUNNING__' ;;
  *"pg_dump"*) printf 'PGDMP' ;;
  *"extversion"*) printf '2.17.2\n' ;;
  *"schema_migrations"*) printf '27\n' ;;
esac
exit 0
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


def _origin(tmp_path: Path, tags: list[str]) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    for name in ("healthsave", "setup.sh"):
        shutil.copy(ROOT / name, origin / name)
    (origin / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (origin / ".gitignore").write_text(".env\nconfig.yaml\n/backups/\n", encoding="utf-8")
    _git(origin, "init", "-q")
    _git(origin, "config", "user.email", "test@example.com")
    _git(origin, "config", "user.name", "Test")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qm", "base")
    _git(origin, "tag", "v1.0.0")
    for tag in tags:
        (origin / "RELEASE").write_text(tag + "\n", encoding="utf-8")
        _git(origin, "add", "RELEASE")
        _git(origin, "commit", "-qm", tag)
        _git(origin, "tag", tag)
    (origin / "RELEASE").write_text("unreleased main\n", encoding="utf-8")
    _git(origin, "add", "RELEASE")
    _git(origin, "commit", "-qm", "main moves on")
    return origin


def _install(
    tmp_path: Path, origin: Path, running: str = "db\napi\nweb\n"
) -> tuple[Path, Path, Path]:
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    _git(checkout, "-c", "advice.detachedHead=false", "checkout", "-q", "v1.0.0")
    (checkout / ".env").write_text("API_KEY=k\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        FAKE_DOCKER.replace("__LOG__", str(log)).replace(
            "__RUNNING__", running.replace("\n", "\\n")
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    return checkout, bin_dir, log


def _update(checkout: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(checkout / "healthsave"), "update", *args],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_update_moves_to_newest_release_after_a_backup(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0", "v1.10.0", "v2.0.0-rc1"])
    checkout, bin_dir, log = _install(tmp_path, origin)

    proc = _update(checkout, bin_dir, "--yes")
    assert proc.returncode == 0, proc.stderr
    assert _git(checkout, "describe", "--tags", "--exact-match") == "v1.10.0"
    assert "Updated to v1.10.0" in proc.stdout + proc.stderr
    assert len(list((checkout / "backups").glob("healthsave-pre-update-*.tar"))) == 1

    calls = log.read_text().splitlines()
    dump = next(i for i, c in enumerate(calls) if "pg_dump" in c)
    up = next(i for i, c in enumerate(calls) if c.startswith("compose up -d --build"))
    assert dump < up, "the backup is taken before the new code starts"
    assert calls[up].split()[4:] == ["db", "api", "web"], "restarts exactly what was running"
    assert (checkout / ".env").read_text() == "API_KEY=k\n"


def test_update_to_a_named_tag(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0", "v1.2.0"])
    checkout, bin_dir, _ = _install(tmp_path, origin)
    proc = _update(checkout, bin_dir, "--to", "v1.1.0", "--yes")
    assert proc.returncode == 0, proc.stderr
    assert _git(checkout, "describe", "--tags", "--exact-match") == "v1.1.0"


def test_update_when_already_current_changes_nothing(tmp_path: Path) -> None:
    origin = _origin(tmp_path, [])
    checkout, bin_dir, log = _install(tmp_path, origin)
    proc = _update(checkout, bin_dir, "--yes")
    assert proc.returncode == 0, proc.stderr
    assert "Already on v1.0.0" in proc.stdout + proc.stderr
    assert not log.exists() or "compose up" not in log.read_text()


def test_update_needs_confirmation_without_a_terminal(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0"])
    checkout, bin_dir, _ = _install(tmp_path, origin)
    proc = _update(checkout, bin_dir)
    assert proc.returncode == 2
    assert "--yes" in proc.stderr
    assert _git(checkout, "describe", "--tags", "--exact-match") == "v1.0.0"


def test_update_refuses_local_changes_to_tracked_files(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0"])
    checkout, bin_dir, _ = _install(tmp_path, origin)
    with (checkout / "docker-compose.yml").open("a") as handle:
        handle.write("# my tweak\n")
    proc = _update(checkout, bin_dir, "--yes")
    assert proc.returncode == 1
    assert "local changes" in proc.stderr
    assert _git(checkout, "describe", "--tags", "--exact-match") == "v1.0.0"


def test_update_rejects_unknown_tag(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0"])
    checkout, bin_dir, _ = _install(tmp_path, origin)
    proc = _update(checkout, bin_dir, "--to", "v9.9.9", "--yes")
    assert proc.returncode == 1
    assert "No release tag called v9.9.9" in proc.stderr


def test_update_with_stack_stopped_only_checks_out(tmp_path: Path) -> None:
    origin = _origin(tmp_path, ["v1.1.0"])
    checkout, bin_dir, log = _install(tmp_path, origin, running="")
    proc = _update(checkout, bin_dir, "--yes")
    assert proc.returncode == 0, proc.stderr
    assert _git(checkout, "describe", "--tags", "--exact-match") == "v1.1.0"
    assert "healthsave up" in proc.stdout + proc.stderr
    assert "compose up" not in log.read_text()
    assert not (checkout / "backups").exists()
