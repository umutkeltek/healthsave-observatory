"""Single LLM transport path — ADR-0003 D6.

Every provider call must go through the one narrator/egress client
(``analysis/llm/client.py``, via litellm) so the egress gate + redaction can
never be bypassed. This guard greps the source tree: ``litellm`` is imported in
exactly one module, and no direct provider SDK is imported anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC_ROOTS = (REPO / "packages" / "py", REPO / "apps")

# The single sanctioned transport module, relative to the repo root.
TRANSPORT = "packages/py/analysis/llm/client.py"

# Direct provider SDKs whose use would route around the egress gate.
_FORBIDDEN_SDK = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(openai|anthropic|google\.generativeai|google\.genai|cohere|mistralai|groq)\b",
    re.MULTILINE,
)
_LITELLM = re.compile(r"^\s*(?:import|from)\s+litellm\b", re.MULTILINE)


def _py_files() -> Iterator[Path]:
    for root in SRC_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def test_litellm_imported_only_in_the_transport_module() -> None:
    offenders = [
        path.relative_to(REPO).as_posix()
        for path in _py_files()
        if path.relative_to(REPO).as_posix() != TRANSPORT
        and _LITELLM.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        f"litellm imported outside {TRANSPORT}: {offenders}. "
        "All LLM calls must go through the single egress-gated transport."
    )


def test_no_direct_provider_sdk_imports() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _py_files():
        match = _FORBIDDEN_SDK.search(path.read_text(encoding="utf-8"))
        if match:
            offenders.append((path.relative_to(REPO).as_posix(), match.group(1)))
    assert offenders == [], (
        f"direct provider SDK import(s) bypass the egress client: {offenders}. "
        "Route all provider calls through analysis/llm/client.py."
    )
