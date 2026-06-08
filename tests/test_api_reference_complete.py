"""Drift guard: API_REFERENCE.md must document every mounted endpoint.

The payload-level reference (root `API_REFERENCE.md`) is the human contract that
pairs with the OpenAPI lock. If a route ships without a line in the reference,
this fails — the reference cannot silently fall behind the surface. Path
parameter *names* are normalized (``{metric_id}`` ~ ``{id}``) so the doc may use
shorthand, but every path skeleton must be present.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "contracts" / "openapi" / "v1.locked.json"
REFERENCE = ROOT / "API_REFERENCE.md"


def _norm(s: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", s)


def test_api_reference_documents_every_endpoint():
    spec = json.loads(LOCK.read_text())
    ref = _norm(REFERENCE.read_text())
    missing = sorted(p for p in spec.get("paths", {}) if _norm(p) not in ref)
    assert not missing, (
        "API_REFERENCE.md is missing these mounted endpoints "
        f"(add a documented entry for each): {missing}"
    )
