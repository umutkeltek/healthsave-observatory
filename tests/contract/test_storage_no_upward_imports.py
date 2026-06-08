"""ARCH-001: storage must not import the API layer (one-way dependency).

The zone rule is ``contracts -> storage -> analysis -> apps/api``. Nothing under
``packages/py/storage/`` may import ``server`` (the ``apps/api`` package, exposed
top-level via the multi-root ``pyproject`` layout) or ``apps.api``.

The audit (ARCH-001) found ``storage/timescale/measurements.py`` importing
``server.ingestion.{mappers,owner,parsers}`` — an inversion the prior
``test_storage_invariant`` (sqlalchemy-only) was blind to. This guard is
forward-only: **zero** violations allowed. Shared pure helpers belong *below*
storage (in ``contracts/`` or ``normalization/``), not in the API layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORAGE_DIR = REPO_ROOT / "packages" / "py" / "storage"

# Top-level package names that belong to the API layer (or above storage).
FORBIDDEN_TOP = {"server", "apps"}


def _imported_top_levels(path: Path) -> set[str]:
    """Top-level module names imported by ``path`` (incl. TYPE_CHECKING imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Only absolute imports carry an upward-dependency risk.
            if node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
    return tops


def test_storage_does_not_import_api_layer():
    violations: dict[str, set[str]] = {}
    for py in sorted(STORAGE_DIR.rglob("*.py")):
        bad = _imported_top_levels(py) & FORBIDDEN_TOP
        if bad:
            violations[str(py.relative_to(REPO_ROOT))] = bad
    assert not violations, (
        "storage/ must not import the API layer (ARCH-001). Move shared pure "
        "helpers down into contracts/ or normalization/ and re-export them from "
        f"server.ingestion.* for the API layer. Violations: {violations}"
    )
