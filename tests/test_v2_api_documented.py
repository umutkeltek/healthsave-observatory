"""DOCS-004: every mounted /api/v2 route must be documented in API.md, so the
public read surface can't silently drift out of the docs again. The v2 plane is
evolving (not a frozen contract), but it must at least be enumerated.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_API_MD = Path(__file__).resolve().parents[1] / "API.md"


def _mounted_v2_paths() -> set[str]:
    from server.main import app

    return {p for r in app.routes if (p := getattr(r, "path", "") or "").startswith("/api/v2")}


def test_every_mounted_v2_route_is_documented_in_api_md():
    doc = _API_MD.read_text()
    missing = sorted(p for p in _mounted_v2_paths() if p not in doc)
    assert missing == [], f"v2 routes missing from API.md: {missing}"
