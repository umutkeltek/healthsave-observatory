"""Two-brain boundary: the statistical engine and the LLM narrator stay apart.

The two-brain rule (ADR-0001 / `docs/HEALTH_DOMAIN_SUPPLEMENT.md`): the
deterministic ``analysis.statistical`` engine PRODUCES structured findings; the
``analysis.llm`` narrator only RENDERS them as prose. Neither imports the other
— the narrator must never compute or judge, and the stats engine must never call
an LLM. This was the one boundary that was discipline-only (an earlier
experiment prompt violated it); this guard makes it a red test instead.

AST, not regex: imports can be relative (``from ..statistical import x``),
aliased, or multiline — ``ast.parse`` walks the real import nodes and we resolve
relative imports to absolute module paths before matching.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO_ROOT / "packages" / "py"
LLM_DIR = PKG_ROOT / "analysis" / "llm"
STATS_DIR = PKG_ROOT / "analysis" / "statistical"


def _imported_modules(file: Path) -> set[str]:
    """Absolute module targets imported by ``file``, resolving relative imports.

    For ``from X import a, b`` we record ``X``, ``X.a`` and ``X.b`` so an import
    of the sibling *package* (``from analysis import statistical``) is caught as
    well as an import of a *module* within it.
    """
    anchor = file.parent.relative_to(PKG_ROOT).parts  # e.g. ('analysis', 'llm')
    targets: set[str] = set()
    tree = ast.parse(file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module or ""
            else:
                base = anchor[: len(anchor) - (node.level - 1)]
                module = ".".join([*base, node.module]) if node.module else ".".join(base)
            if module:
                targets.add(module)
                targets.update(f"{module}.{alias.name}" for alias in node.names)
    return targets


@pytest.mark.parametrize(
    ("zone", "forbidden", "why"),
    [
        (LLM_DIR, "analysis.statistical", "the narrator must not compute/judge findings"),
        (STATS_DIR, "analysis.llm", "the stats engine must not call the LLM"),
    ],
)
def test_two_brain_zones_do_not_import_each_other(zone: Path, forbidden: str, why: str) -> None:
    offenders: list[str] = []
    for file in sorted(zone.rglob("*.py")):
        for target in _imported_modules(file):
            if target == forbidden or target.startswith(f"{forbidden}."):
                offenders.append(f"{file.relative_to(REPO_ROOT)} imports {target}")
    assert not offenders, f"two-brain boundary broken — {why}:\n" + "\n".join(offenders)
