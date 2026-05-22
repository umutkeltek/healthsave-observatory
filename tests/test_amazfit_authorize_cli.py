"""Tests for scripts/amazfit_authorize.py — H-cli.

The interactive ``main()`` is I/O glue (DB engine + stdin/stdout) and
not unit-tested. ``parse_args``, ``materialize_token_from_args``, and
``run_authorize_flow`` are the testable seams.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "py"))
sys.path.insert(0, str(ROOT / "scripts"))

import amazfit_authorize  # noqa: E402
from auth import OAuthToken  # noqa: E402

from plugins.sources.amazfit.auth import AmazfitAuthError  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _RecordingSession:
    commits: int = 0
    executes: list[Any] = field(default_factory=list)

    async def execute(self, statement, params=None):
        self.executes.append({"statement": statement, "params": params})

    async def commit(self):
        self.commits += 1


@dataclass
class _RecordingTokenStore:
    puts: list[dict[str, Any]] = field(default_factory=list)

    async def put_token(self, session, token, *, event_kind="authorized"):
        self.puts.append({"token": token, "event_kind": event_kind})


# ──────────────────────────────────────────────────────────────────────
# parse_args
# ──────────────────────────────────────────────────────────────────────


def test_parse_args_huami_token_mode():
    args = amazfit_authorize.parse_args(
        ["--from-huami-token-stdout", "/tmp/zepp.txt", "--region", "eu"]
    )
    assert args.from_huami_token_stdout == Path("/tmp/zepp.txt")
    assert args.from_token is None
    assert args.region == "eu"


def test_parse_args_from_token_mode():
    args = amazfit_authorize.parse_args(
        ["--from-token", "TOKEN_VAL", "--user-id", "42", "--region", "us"]
    )
    assert args.from_token == "TOKEN_VAL"
    assert args.user_id == "42"
    assert args.from_huami_token_stdout is None


def test_parse_args_requires_a_source(capsys):
    with pytest.raises(SystemExit):
        amazfit_authorize.parse_args([])


def test_parse_args_rejects_both_sources(capsys):
    with pytest.raises(SystemExit):
        amazfit_authorize.parse_args(
            ["--from-token", "X", "--user-id", "42", "--from-huami-token-stdout", "/x"]
        )


def test_parse_args_rejects_unknown_region(capsys):
    with pytest.raises(SystemExit):
        amazfit_authorize.parse_args(
            ["--from-token", "X", "--user-id", "42", "--region", "atlantis"]
        )


# ──────────────────────────────────────────────────────────────────────
# materialize_token_from_args
# ──────────────────────────────────────────────────────────────────────


def test_materialize_token_from_token_string_happy_path():
    args = amazfit_authorize.parse_args(
        ["--from-token", "TOKEN_BLOB", "--user-id", "3311629755", "--region", "us"]
    )
    token = amazfit_authorize.materialize_token_from_args(args)
    assert isinstance(token, OAuthToken)
    assert token.access_token == "TOKEN_BLOB"
    assert token.metadata["user_id"] == "3311629755"
    assert token.metadata["region"] == "us"
    assert token.metadata["base_url"] == "https://api-mifit-us3.zepp.com"


def test_materialize_token_from_token_string_missing_user_id_raises():
    args = amazfit_authorize.parse_args(["--from-token", "TOKEN_BLOB"])
    with pytest.raises(AmazfitAuthError) as exc:
        amazfit_authorize.materialize_token_from_args(args)
    assert "user-id" in str(exc.value).lower() or "user_id" in str(exc.value)


def test_materialize_token_from_huami_token_file(tmp_path):
    output_file = tmp_path / "zepp.txt"
    output_file.write_text(
        "2026-05-22 23:10:11.395 | INFO | huami_token.zepp:login:71 - Logged in! User id: 42\n"
        "No logout!\n"
        "app_token=PARSED_FROM_FILE\n"
        "login_token=intermediate\n"
    )
    args = amazfit_authorize.parse_args(
        ["--from-huami-token-stdout", str(output_file), "--region", "us"]
    )
    token = amazfit_authorize.materialize_token_from_args(args)
    assert token.access_token == "PARSED_FROM_FILE"
    assert token.metadata["user_id"] == "42"


def test_materialize_token_from_huami_token_file_missing_path_raises(tmp_path):
    args = amazfit_authorize.parse_args(
        ["--from-huami-token-stdout", str(tmp_path / "does-not-exist.txt")]
    )
    with pytest.raises(AmazfitAuthError) as exc:
        amazfit_authorize.materialize_token_from_args(args)
    assert "could not read" in str(exc.value)


def test_materialize_token_from_huami_token_file_malformed_raises(tmp_path):
    output_file = tmp_path / "zepp.txt"
    output_file.write_text("nothing useful here\n")
    args = amazfit_authorize.parse_args(["--from-huami-token-stdout", str(output_file)])
    with pytest.raises(AmazfitAuthError):
        amazfit_authorize.materialize_token_from_args(args)


# ──────────────────────────────────────────────────────────────────────
# run_authorize_flow
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_authorize_flow_persists_token_and_commits():
    args = amazfit_authorize.parse_args(["--from-token", "T", "--user-id", "42", "--region", "us"])
    token = amazfit_authorize.materialize_token_from_args(args)
    session = _RecordingSession()
    store = _RecordingTokenStore()
    out = await amazfit_authorize.run_authorize_flow(
        token=token, session=session, token_store=store
    )
    assert out is token
    assert session.commits == 1
    assert len(store.puts) == 1
    assert store.puts[0]["event_kind"] == "authorized"
    assert store.puts[0]["token"] is token


# ──────────────────────────────────────────────────────────────────────
# anti — never print the secret
# ──────────────────────────────────────────────────────────────────────


def test_cli_module_source_does_not_print_access_token_directly():
    """Anti-regression: the success message prints only token LENGTH +
    expiry, never the token value itself.
    """
    src = (ROOT / "scripts" / "amazfit_authorize.py").read_text()
    stripped = src.replace("len(stored.access_token)", "")
    assert "stored.access_token" not in stripped, (
        "amazfit_authorize.py must not print stored.access_token directly — "
        "only its length is acceptable."
    )
