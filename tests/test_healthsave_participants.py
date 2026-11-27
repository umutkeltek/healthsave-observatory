"""``healthsave participants`` and ``python -m scripts.participants`` (migration 029)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from storage.timescale import api_keys
from storage.timescale.api_keys import ApiKeyError, ApiKeyRecord

from scripts import participants as script

ROOT = Path(__file__).resolve().parents[1]
KEY = "a1" * 24
OWNER = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00"


# ─── bash CLI ──────────────────────────────────────────────────────────


def _checkout(tmp_path: Path, env_text: str | None = "API_KEY=legacy\n") -> tuple[Path, Path]:
    checkout = tmp_path / "checkout"
    bin_dir = tmp_path / "bin"
    checkout.mkdir()
    bin_dir.mkdir()
    for name in ("healthsave", "setup.sh", ".env.example", "config.yaml.example"):
        shutil.copy(ROOT / name, checkout / name)
    if env_text is not None:
        (checkout / ".env").write_text(env_text, encoding="utf-8")
    return checkout, bin_dir


def _fake_docker(bin_dir: Path, log: Path, *, api_running: bool = True, exec_body: str) -> None:
    services = "api\\ndb" if api_running else "db"
    script_text = f"""#!/usr/bin/env bash
echo "$*" >> "{log}"
if [ "$1" = "info" ]; then exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then printf '{services}\\n'; exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "exec" ]; then
{exec_body}
fi
exit 0
"""
    path = bin_dir / "docker"
    path.write_text(script_text, encoding="utf-8")
    path.chmod(0o755)


def _run(checkout: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(checkout / "healthsave"), *args],
        cwd="/tmp",
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        text=True,
        capture_output=True,
        timeout=20,
        stdin=subprocess.DEVNULL,
    )


_ADD_OK = f"""printf 'key={KEY}\\nowner_id={OWNER}\\nlabel=Alice Smith\\nscope=ingest\\n'
exit 0"""


def test_add_prints_url_key_and_the_pair_block(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    log = tmp_path / "docker.log"
    _fake_docker(bin_dir, log, exec_body=_ADD_OK)
    proc = _run(
        checkout, bin_dir, "participants", "add", "Alice Smith", "--url", "https://obs.example"
    )
    assert proc.returncode == 0, proc.stderr
    assert "Added Alice Smith (owner " + OWNER + ")" in proc.stdout
    assert re.search(r"Server URL:\s+https://obs\.example", proc.stdout)
    assert re.search(rf"API key:\s+{KEY}", proc.stdout)
    assert "HealthSave app" in proc.stdout  # the same block `pair` prints
    calls = log.read_text()
    assert (
        "compose exec -T api python -m scripts.participants add Alice Smith --scope ingest" in calls
    )
    assert KEY not in calls  # the plaintext never rides on a command line


def test_add_read_key_has_no_phone_pairing_block(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    log = tmp_path / "docker.log"
    _fake_docker(bin_dir, log, exec_body=_ADD_OK)
    proc = _run(
        checkout, bin_dir, "participants", "add", "Alice", "--read", "--url", "http://h:8000"
    )
    assert proc.returncode == 0, proc.stderr
    assert "--scope read" in log.read_text()
    assert "Read-only key" in proc.stdout
    assert re.search(rf"API key:\s+{KEY}", proc.stdout)
    assert "HealthSave app" not in proc.stdout


def test_add_refusal_from_the_container_is_exit_2(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    refuse = """echo "error: 'Alice' already has a live ingest key; revoke it first" >&2
exit 2"""
    _fake_docker(bin_dir, tmp_path / "docker.log", exec_body=refuse)
    proc = _run(checkout, bin_dir, "participants", "add", "Alice")
    assert proc.returncode == 2
    assert "already has a live ingest key" in proc.stderr
    assert "API key:" not in proc.stdout


def test_add_needs_the_api_running(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    _fake_docker(bin_dir, tmp_path / "docker.log", api_running=False, exec_body="exit 0")
    proc = _run(checkout, bin_dir, "participants", "add", "Alice")
    assert proc.returncode == 1
    assert "healthsave up" in proc.stderr


@pytest.mark.parametrize(
    "args",
    [("participants", "add"), ("participants", "add", "A", "B"), ("participants", "bogus")],
)
def test_bad_arguments_are_exit_2(tmp_path: Path, args: tuple[str, ...]) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    _fake_docker(bin_dir, tmp_path / "docker.log", exec_body="exit 0")
    assert _run(checkout, bin_dir, *args).returncode == 2


def test_add_requires_env_file(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path, env_text=None)
    _fake_docker(bin_dir, tmp_path / "docker.log", exec_body="exit 0")
    proc = _run(checkout, bin_dir, "participants", "add", "Alice")
    assert proc.returncode == 1
    assert "healthsave setup basic" in proc.stderr


def test_revoke_and_list_go_through_the_container(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    log = tmp_path / "docker.log"
    body = """case "$*" in
  *revoke*) echo "revoked=1" ;;
  *list*) echo "NAME   STATUS" ;;
esac
exit 0"""
    _fake_docker(bin_dir, log, exec_body=body)
    revoked = _run(checkout, bin_dir, "participants", "revoke", "Alice")
    assert revoked.returncode == 0, revoked.stderr
    assert "Revoked 1 key(s) for Alice" in revoked.stdout
    listed = _run(checkout, bin_dir, "participants", "list")
    assert listed.returncode == 0 and "NAME   STATUS" in listed.stdout
    calls = log.read_text()
    assert "scripts.participants revoke Alice" in calls
    assert "scripts.participants list" in calls


def test_help_lists_the_command(tmp_path: Path) -> None:
    checkout, bin_dir = _checkout(tmp_path)
    proc = _run(checkout, bin_dir, "--help")
    assert re.search(r"participants add\|list\|revoke", proc.stdout)


# ─── python -m scripts.participants ────────────────────────────────────


class _Session:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


async def test_script_add_stores_only_the_hash_and_prints_the_key_once(monkeypatch, capsys):
    stored: dict = {}

    async def _create(session, *, label, scope, key_hash, primary=False):
        stored.update(label=label, scope=scope, key_hash=key_hash, primary=primary)
        return ApiKeyRecord(id=UUID(int=1), label=label, scope=scope, owner_id=UUID(OWNER))

    monkeypatch.setattr(api_keys, "create_api_key", _create)
    session = _Session()
    assert await script._add(session, "Alice", "ingest") == 0
    out = capsys.readouterr().out
    key = re.search(r"^key=([0-9a-f]{48})$", out, re.M).group(1)
    assert stored["key_hash"] == api_keys.hash_api_key(key)
    assert key not in stored.values()
    assert f"owner_id={OWNER}" in out and session.committed


async def test_script_add_primary_mints_a_read_key_for_the_primary_person(monkeypatch, capsys):
    stored: dict = {}

    async def _create(session, *, label, scope, key_hash, primary=False):
        stored.update(label=label, scope=scope, primary=primary)
        return ApiKeyRecord(id=UUID(int=2), label=label, scope=scope, owner_id=UUID(int=1))

    monkeypatch.setattr(api_keys, "create_api_key", _create)
    session = _Session()
    assert await script._add(session, "MCP read key", "read", True) == 0
    assert stored == {"label": "MCP read key", "scope": "read", "primary": True}
    assert script._parser().parse_args(["add", "x", "--scope", "read", "--primary"]).primary


async def test_script_add_refusal_rolls_back_and_exits_2(monkeypatch, capsys):
    async def _create(session, **kwargs):
        raise ApiKeyError("'Alice' already has a live ingest key; revoke it first")

    monkeypatch.setattr(api_keys, "create_api_key", _create)
    session = _Session()
    assert await script._add(session, "Alice", "ingest") == 2
    captured = capsys.readouterr()
    assert "key=" not in captured.out and "already has a live" in captured.err
    assert session.rolled_back and not session.committed


async def test_script_revoke_unknown_label_exits_1(monkeypatch, capsys):
    async def _revoke(session, label):
        return 0

    monkeypatch.setattr(api_keys, "revoke_label", _revoke)
    assert await script._revoke(_Session(), "Nobody") == 1
    assert "no live key" in capsys.readouterr().err


async def test_script_list_shows_participants_not_the_primary(monkeypatch, capsys):
    async def _owners(session):
        return [
            {
                "id": "0",
                "label": None,
                "is_default": True,
                "active": True,
                "scopes": [],
                "last_ingest_at": None,
            },
            {
                "id": OWNER,
                "label": "Alice",
                "is_default": False,
                "active": False,
                "scopes": [],
                "last_ingest_at": datetime(2026, 11, 2, 7, 55, tzinfo=UTC),
            },
        ]

    monkeypatch.setattr(api_keys, "list_owners", _owners)
    assert await script._list(_Session()) == 0
    out = capsys.readouterr().out
    assert "Alice" in out and "revoked" in out and "2026-11-02 07:55 UTC" in out
    assert out.count("\n") == 2  # header + one participant


def test_script_needs_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert script.main(["list"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err
