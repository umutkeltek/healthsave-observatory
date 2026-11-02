"""healthsave update --rollback (Care), on a real git origin with a fake docker.

Every update records where it came from; the rollback reads that record.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.licence_testkit import make_key, mint, python_shim
from tests.test_healthsave_update import _git, _install, _origin

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git is required")


class Stack:
    def __init__(self, tmp_path: Path, running: str = "db\napi\nweb\n") -> None:
        origin = _origin(tmp_path, ["v1.1.0", "v1.2.0"])
        self.checkout, self.bin, self.log = _install(tmp_path, origin, running=running)
        self.key = make_key()
        self.shim = python_shim(self.bin, self.key)

    def license(self, **overrides) -> None:
        (self.checkout / "healthsave.license").write_text(mint(self.key, **overrides))

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HEALTHSAVE_PYTHON": str(self.shim),
        }
        env.pop("HEALTHSAVE_LICENSE_FILE", None)
        return subprocess.run(
            [str(self.checkout / "healthsave"), "update", *args],
            cwd="/tmp",
            env=env,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=60,
        )

    def tag(self) -> str:
        return _git(self.checkout, "describe", "--tags", "--exact-match")

    def record(self) -> Path:
        return Path(_git(self.checkout, "rev-parse", "--absolute-git-dir")) / (
            "healthsave-last-update"
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


def _record_values(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def test_every_update_records_where_it_came_from(tmp_path):
    stack = Stack(tmp_path)
    v100 = _git(stack.checkout, "rev-parse", "HEAD")
    assert stack.run("--yes").returncode == 0
    values = _record_values(stack.record())
    assert values["format"] == "healthsave-update-1"
    assert values["from_commit"] == v100
    assert values["from_label"] == "v1.0.0"
    assert values["to_tag"] == "v1.2.0"
    assert values["to_commit"] == _git(stack.checkout, "rev-parse", "HEAD")
    assert values["services"] == "db api web"
    assert values["backup"].startswith("backups/healthsave-pre-update-")
    assert _git(stack.checkout, "status", "--porcelain") == "", "the record is never tracked"


def test_rollback_needs_a_licence_and_changes_nothing_without_one(tmp_path):
    stack = Stack(tmp_path)
    assert stack.run("--yes").returncode == 0
    before = len(stack.calls())
    proc = stack.run("--rollback", "--yes")
    assert proc.returncode == 1
    assert "part of Observatory Care" in proc.stderr
    assert stack.tag() == "v1.2.0"
    assert stack.calls()[before:] == []


def test_rollback_returns_to_the_previous_release_and_restarts_what_ran(tmp_path):
    stack = Stack(tmp_path)
    assert stack.run("--yes").returncode == 0
    stack.license()
    before = len(stack.calls())

    proc = stack.run("--rollback", "--yes")
    assert proc.returncode == 0, proc.stderr
    assert stack.tag() == "v1.0.0"
    assert "Rolled back to v1.0.0" in proc.stdout
    assert "healthsave restore backups/healthsave-pre-update-" in proc.stdout
    up = [c for c in stack.calls()[before:] if c.startswith("compose up -d --build")]
    assert up == ["compose up -d --build db api web"]
    assert not any("pg_dump" in c for c in stack.calls()[before:]), "no new backup, no restore"
    assert not stack.record().exists()
    assert stack.record().with_name("healthsave-last-update.rolled-back").exists()

    again = stack.run("--rollback", "--yes")
    assert again.returncode == 1
    assert "no update to roll back" in again.stderr


def test_rollback_of_an_update_made_with_the_stack_stopped_only_checks_out(tmp_path):
    stack = Stack(tmp_path, running="")
    assert stack.run("--yes").returncode == 0
    stack.license()
    proc = stack.run("--rollback", "--yes")
    assert proc.returncode == 0, proc.stderr
    assert stack.tag() == "v1.0.0"
    assert "healthsave up" in proc.stdout
    assert not any(c.startswith("compose up") for c in stack.calls())


def test_rollback_refuses_when_the_checkout_moved_after_the_update(tmp_path):
    stack = Stack(tmp_path)
    assert stack.run("--yes").returncode == 0
    _git(stack.checkout, "-c", "advice.detachedHead=false", "checkout", "-q", "v1.1.0")
    stack.license()
    proc = stack.run("--rollback", "--yes")
    assert proc.returncode == 1
    assert "no longer on v1.2.0" in proc.stderr
    assert stack.tag() == "v1.1.0"


def test_rollback_without_any_update_says_so(tmp_path):
    stack = Stack(tmp_path)
    stack.license()
    proc = stack.run("--rollback", "--yes")
    assert proc.returncode == 1
    assert "no update to roll back" in proc.stderr


def test_rollback_needs_confirmation_without_a_terminal(tmp_path):
    stack = Stack(tmp_path)
    assert stack.run("--yes").returncode == 0
    stack.license()
    proc = stack.run("--rollback")
    assert proc.returncode == 2
    assert "--yes" in proc.stderr
    assert stack.tag() == "v1.2.0"


def test_rollback_takes_no_target(tmp_path):
    stack = Stack(tmp_path)
    stack.license()
    proc = stack.run("--rollback", "--to", "v1.1.0", "--yes")
    assert proc.returncode == 2


def test_plain_update_stays_free(tmp_path):
    stack = Stack(tmp_path)
    proc = stack.run("--yes")
    assert proc.returncode == 0, proc.stderr
    assert stack.tag() == "v1.2.0"
    assert not (stack.checkout / "healthsave.license").exists()
