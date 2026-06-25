from __future__ import annotations

import os
import pty
import select
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_until(master_fd: int, needle: str, timeout: float = 2.0) -> tuple[str, bool]:
    deadline = time.monotonic() + timeout
    output = b""
    needle_bytes = needle.encode()

    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([master_fd], [], [], min(0.05, remaining))
        if not readable:
            continue
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if needle_bytes in output:
            return output.decode(errors="replace"), True

    return output.decode(errors="replace"), needle_bytes in output


def _spawn_prompt_command(command: str) -> tuple[subprocess.Popen[bytes], int]:
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["HEALTHSAVE_SETUP_TEST"] = "1"
    proc = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=ROOT,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    return proc, master_fd


def _finish_prompt_process(proc: subprocess.Popen[bytes], master_fd: int) -> str:
    os.write(master_fd, b"\r")
    output, _ = _read_until(master_fd, "VALUE=<", timeout=2.0)
    proc.wait(timeout=2)
    return output


def test_prompt_default_is_visible_inside_command_substitution() -> None:
    proc, master_fd = _spawn_prompt_command(
        "source ./setup.sh; "
        'value="$(prompt_default "Database password" "generated")"; '
        'printf "VALUE=<%s>\\n" "$value"'
    )
    try:
        output, visible = _read_until(master_fd, "Database password", timeout=1.0)
        assert visible, f"prompt was not visible before input; output={output!r}"

        output += _finish_prompt_process(proc, master_fd)
        assert "VALUE=<generated>" in output
    finally:
        if proc.poll() is None:
            proc.terminate()
        os.close(master_fd)


def test_prompt_default_returns_typed_value_without_prompt_text() -> None:
    proc, master_fd = _spawn_prompt_command(
        "source ./setup.sh; "
        'value="$(prompt_default "Grafana admin password" "generated")"; '
        'printf "VALUE=<%s>\\n" "$value"'
    )
    try:
        output, visible = _read_until(master_fd, "Grafana admin password", timeout=1.0)
        assert visible, f"prompt was not visible before input; output={output!r}"

        os.write(master_fd, b"custom-secret\r")
        tail, _ = _read_until(master_fd, "VALUE=<custom-secret>", timeout=2.0)
        output += tail
        assert "VALUE=<custom-secret>" in output
        proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            proc.terminate()
        os.close(master_fd)


def test_prompt_yes_no_is_visible_and_uses_default() -> None:
    proc, master_fd = _spawn_prompt_command(
        "source ./setup.sh; "
        'if prompt_yes_no "Enable local LLM (Ollama) AI analysis?" "y/N"; '
        'then printf "VALUE=<yes>\\n"; else printf "VALUE=<no>\\n"; fi'
    )
    try:
        output, visible = _read_until(master_fd, "Enable local LLM", timeout=1.0)
        assert visible, f"prompt was not visible before input; output={output!r}"

        output += _finish_prompt_process(proc, master_fd)
        assert "VALUE=<no>" in output
    finally:
        if proc.poll() is None:
            proc.terminate()
        os.close(master_fd)


def test_prompt_default_noninteractive_uses_default_without_blocking() -> None:
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            "HEALTHSAVE_SETUP_TEST=1 source ./setup.sh; "
            'value="$(prompt_default "API key" "generated")"; '
            'printf "%s" "$value"',
        ],
        cwd=ROOT,
        input="",
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )

    assert proc.stdout == "generated"
