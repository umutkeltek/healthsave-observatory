"""``healthsave mcp``: one setup line per AI client, a read-only key, a check.

The key is minted inside the API container (never on a command line), kept in
.env as MCP_READ_KEY, printed into the setup lines, and passed to the check on
stdin. The setup pins the MCP server to the release the stack runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_healthsave_participants import _checkout, _fake_docker, _run

KEY = "b2" * 24
URL = "http://192.168.1.20:8000"
_OWNER = "00000000-0000-0000-0000-000000000001"
_MINT = f"""case "$*" in
  *"scripts.participants add MCP read key --scope read --primary"*)
    printf 'key={KEY}\\nowner_id={_OWNER}\\nlabel=MCP read key\\nscope=read\\n'
    exit 0 ;;
  *"scripts.participants revoke MCP read key"*) printf 'revoked=1\\n'; exit 0 ;;
  *"healthsave-mcp"*)
    cat > "$(dirname "$0")/stdin.txt"
    echo "[OK] MCP server answers: 8 read-only tools"
    exit 0 ;;
esac
exit 0"""


def _setup(tmp_path: Path, env_text: str = "API_KEY=legacy\n", **kw):
    checkout, bin_dir = _checkout(tmp_path, env_text)
    (checkout / "docker-compose.yml").write_text(
        "services:\n  api:\n    image: ghcr.io/umutkeltek/healthsave-observatory:"
        "${HEALTHSAVE_VERSION:-v1.4.0}\n"
    )
    log = tmp_path / "docker.log"
    _fake_docker(bin_dir, log, exec_body=_MINT, **kw)
    return checkout, bin_dir, log


def test_first_run_mints_a_read_key_saves_it_and_prints_the_claude_code_line(tmp_path) -> None:
    checkout, bin_dir, log = _setup(tmp_path)
    proc = _run(checkout, bin_dir, "mcp", "--url", URL)
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text()
    assert (
        "compose exec -T api python -m scripts.participants add MCP read key --scope read --primary"
        in calls
    )
    assert KEY not in calls  # minted in the container, never on a command line
    assert f"MCP_READ_KEY={KEY}" in (checkout / ".env").read_text()
    from_ = (
        "git+https://github.com/umutkeltek/healthsave-observatory@v1.4.0#subdirectory=packages/mcp"
    )
    line = (
        f"claude mcp add healthsave -e HEALTHSAVE_URL={URL} -e HEALTHSAVE_API_KEY={KEY} "
        f'-- uvx --from "{from_}" healthsave-mcp'
    )
    assert line in proc.stdout
    assert f'"args": ["--from", "{from_}", "healthsave-mcp"]' in proc.stdout  # Claude Desktop
    assert (
        "docker run -i --rm -e HEALTHSAVE_URL -e HEALTHSAVE_API_KEY "
        "ghcr.io/umutkeltek/healthsave-observatory:v1.4.0 /opt/healthsave-mcp/bin/healthsave-mcp"
        in proc.stdout
    )
    assert "ChatGPT - not yet" in proc.stdout


def test_a_saved_key_is_reused_without_touching_docker(tmp_path) -> None:
    checkout, bin_dir, log = _setup(tmp_path, f"API_KEY=legacy\nMCP_READ_KEY={KEY}\n")
    proc = _run(checkout, bin_dir, "mcp", "--url", URL, "--client", "claude-code")
    assert proc.returncode == 0, proc.stderr
    assert "scripts.participants" not in (log.read_text() if log.exists() else "")
    assert f"HEALTHSAVE_API_KEY={KEY}" in proc.stdout
    assert "Claude Desktop" not in proc.stdout and "docker run" not in proc.stdout


def test_the_setup_pins_the_release_the_stack_runs(tmp_path) -> None:
    checkout, bin_dir, _ = _setup(
        tmp_path, f"API_KEY=legacy\nMCP_READ_KEY={KEY}\nHEALTHSAVE_VERSION=v1.5.2\n"
    )
    proc = _run(checkout, bin_dir, "mcp", "--url", URL, "--client", "claude-code")
    assert "healthsave-observatory@v1.5.2#subdirectory=packages/mcp" in proc.stdout
    # A non-tag value (a dev override) falls back to the compose default.
    (checkout / ".env").write_text(f"API_KEY=legacy\nMCP_READ_KEY={KEY}\nHEALTHSAVE_VERSION=dev\n")
    proc = _run(checkout, bin_dir, "mcp", "--url", URL, "--client", "claude-code")
    assert "healthsave-observatory@v1.4.0#subdirectory" in proc.stdout


def test_minting_needs_the_api_running(tmp_path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path, api_running=False)
    proc = _run(checkout, bin_dir, "mcp", "--url", URL)
    assert proc.returncode == 1
    assert "not running" in proc.stderr + proc.stdout
    assert "MCP_READ_KEY" not in (checkout / ".env").read_text()


def test_rotate_revokes_then_mints_and_replaces_the_saved_key(tmp_path) -> None:
    checkout, bin_dir, log = _setup(tmp_path, "API_KEY=legacy\nMCP_READ_KEY=" + "0" * 48 + "\n")
    proc = _run(checkout, bin_dir, "mcp", "key", "--rotate")
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text().splitlines()
    revoke = next(i for i, c in enumerate(calls) if "revoke MCP read key" in c)
    mint = next(i for i, c in enumerate(calls) if "add MCP read key" in c)
    assert revoke < mint
    env = (checkout / ".env").read_text()
    assert f"MCP_READ_KEY={KEY}" in env and "0" * 48 not in env
    assert re.search(rf"Read key:\s+{KEY}", proc.stdout)


def test_check_passes_the_key_on_stdin_not_argv(tmp_path) -> None:
    checkout, bin_dir, log = _setup(tmp_path, f"API_KEY=legacy\nMCP_READ_KEY={KEY}\n")
    proc = _run(checkout, bin_dir, "mcp", "--check")
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text()
    assert (
        "compose exec -T api sh -c" in calls and "/opt/healthsave-mcp/bin/healthsave-mcp" in calls
    )
    assert "HEALTHSAVE_URL=http://127.0.0.1:8000" in calls
    assert KEY not in calls
    assert (bin_dir / "stdin.txt").read_text().strip() == KEY
    assert "[OK] MCP server answers" in proc.stdout


def test_bad_arguments_and_missing_env(tmp_path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path)
    for args in (("mcp", "--client", "gemini"), ("mcp", "--bogus"), ("mcp", "--rotate")):
        assert _run(checkout, bin_dir, *args).returncode == 2, args
    (checkout / ".env").unlink()
    assert _run(checkout, bin_dir, "mcp").returncode == 1


def test_help_names_the_command(tmp_path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path)
    assert re.search(r"^\s+mcp \[key\|--check\]", _run(checkout, bin_dir, "--help").stdout, re.M)
    usage = _run(checkout, bin_dir, "mcp", "--help").stdout
    assert "healthsave mcp key [--rotate]" in usage and "read-only" in usage.lower()


def test_mcp_key_fails_loudly_when_it_cannot_mint(tmp_path) -> None:
    checkout, bin_dir, _ = _setup(tmp_path, api_running=False)
    proc = _run(checkout, bin_dir, "mcp", "key")
    assert proc.returncode != 0
    assert "Read key:" not in proc.stdout  # never an empty key and exit 0


def test_a_live_key_missing_from_env_points_at_rotate(tmp_path) -> None:
    checkout, bin_dir = _checkout(tmp_path, "API_KEY=legacy\n")
    log = tmp_path / "docker.log"
    refuse = """echo "error: 'MCP read key' already has a live read key; revoke it first" >&2
exit 2"""
    _fake_docker(bin_dir, log, exec_body=refuse)
    proc = _run(checkout, bin_dir, "mcp", "--url", URL)
    assert proc.returncode == 2
    assert "healthsave mcp key --rotate" in proc.stderr
