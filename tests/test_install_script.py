"""install.sh installs the newest release tag, never main."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git is required")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout


def _repo_with_tags(tmp_path: Path, tags: list[str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("setup.sh", "docker-compose.yml"):
        (repo / name).write_text("\n", encoding="utf-8")
    cli = repo / "healthsave"
    cli.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    cli.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    for tag in tags:
        (repo / "setup.sh").write_text(f"# {tag}\n", encoding="utf-8")
        _git(repo, "commit", "-qam", tag)
        _git(repo, "tag", tag)
    (repo / "setup.sh").write_text("# unreleased main\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "main moves on")
    return repo


def _install(
    tmp_path: Path, repo: Path, **extra_env: str
) -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    target = tmp_path / "target"
    proc = subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HEALTHSAVE_OBSERVATORY_REPO": str(repo),
            "HEALTHSAVE_OBSERVATORY_HOME": str(target),
            **extra_env,
        },
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
    )
    return proc, target


def test_install_checks_out_newest_release_tag(tmp_path: Path) -> None:
    repo = _repo_with_tags(tmp_path, ["v1.9.0", "v1.10.0", "v2.0.0-rc1"])
    proc, target = _install(tmp_path, repo)
    assert _git(target, "tag", "--points-at", "HEAD").split() == ["v1.10.0"], proc.stderr
    assert "Checking out v1.10.0" in proc.stderr


def test_install_honors_explicit_ref(tmp_path: Path) -> None:
    repo = _repo_with_tags(tmp_path, ["v1.0.0", "v1.1.0"])
    proc, target = _install(tmp_path, repo, HEALTHSAVE_OBSERVATORY_REF="v1.0.0")
    assert _git(target, "tag", "--points-at", "HEAD").split() == ["v1.0.0"], proc.stderr


def test_install_without_release_tags_fails_and_cleans_up(tmp_path: Path) -> None:
    repo = _repo_with_tags(tmp_path, [])
    proc, target = _install(tmp_path, repo)
    assert proc.returncode != 0
    assert "no vX.Y.Z release tag" in proc.stderr
    assert not target.exists()
