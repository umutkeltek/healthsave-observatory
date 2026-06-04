"""apps/agents + apps/worker + plugins/agents import-boundary invariant.

Phase 7-C invariant — the agents service may not depend on the API
service's internals. The boundary keeps proposal-emitting code from
reaching for route handlers, ingestion code, or FastAPI app state — the
exact dependency that would couple agent lifecycle to API uptime and
make Phase 8 dashboard split impossible.

The worker follows the same rule: it may depend on shared packages and
storage ports, but not API internals. Otherwise scheduler uptime becomes
coupled to the FastAPI service's private module layout.

Allowed exception: ``server.db.session`` (engine bootstrap) — precedent
set by :mod:`worker.listener` in :mod:`tests.contract.test_storage_invariant`.
The engine factory is a shared bootstrap concern, not API internals.

Why AST and not regex: import statements can be aliased
(``from server import db as _db``), multiline
(``from server import (\n    db,\n    api,\n)``), or hidden behind
``importlib.import_module(...)``. ``ast.parse`` walks the actual import
nodes; the alternative would silently miss any of those forms.

The test fails on:

  1. Any ``import server`` / ``from server.X import ...`` /
     ``import server.X`` inside ``apps/agents/`` or ``apps/worker/`` that is
     not in the service's allowlist.
  2. ANY ``server.*`` import inside ``plugins/agents/`` (no allowlist).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_AGENTS = REPO_ROOT / "apps" / "agents"
APPS_WORKER = REPO_ROOT / "apps" / "worker"
PLUGINS_AGENTS = REPO_ROOT / "plugins" / "agents"


# ---- Allowlist ---------------------------------------------------
#
# Each allowed ``server.*`` module that apps/agents/ is permitted to
# import. plugins/agents/ has no allowlist — agent plugin code must
# never reach into the API service.
#
# Goal: this list stays at one entry (the engine bootstrap). If a new
# entry feels necessary, the right answer is almost always to lift the
# shared concept into ``packages/py/`` (storage, contracts, plugin_sdk).
APPS_AGENTS_ALLOWLIST: set[str] = {
    "server.db.session",
}
APPS_WORKER_ALLOWLIST: set[str] = {
    "server.db.session",
}


def _collect_server_imports(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, dotted_name)`` for every ``server.*`` import
    in the file. Walks the AST — doesn't depend on whitespace, aliases,
    or multiline form.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "server" or alias.name.startswith("server."):
                    out.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "server" or module.startswith("server."):
                # ImportFrom imports specific symbols; the dotted name we
                # care about is the module, NOT the symbols.
                out.append((node.lineno, module))
    return out


def _walk_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*.py")
        # Exclude __pycache__ etc. — rglob already skips files inside
        # dirs that start with '.', but explicit is safer.
        if "__pycache__" not in p.parts
    )


def _assert_only_allowed_server_imports(
    *,
    root: Path,
    allowlist: set[str],
    service_name: str,
) -> None:
    """Every server-namespaced import inside ``root`` must be in
    the allowlist. New violations fail this test — fix by importing
    from packages/py/ instead, or by adding to the allowlist with a
    deferral note.
    """
    violations: list[tuple[Path, int, str]] = []
    for py in _walk_python_files(root):
        for lineno, dotted in _collect_server_imports(py):
            if dotted not in allowlist:
                violations.append((py.relative_to(REPO_ROOT), lineno, dotted))
    assert not violations, (
        f"{service_name} imported disallowed server.* modules:\n"
        + "\n".join(f"  - {path}:{ln} imports {dotted}" for path, ln, dotted in violations)
        + "\n\nLift the shared symbol into packages/py/ (storage, contracts, plugin_sdk), "
        "or add the module to the service allowlist in this file with a deferral note. "
        f"{service_name} must not depend on apps/api/server internals."
    )


def test_apps_agents_only_allowed_server_imports() -> None:
    _assert_only_allowed_server_imports(
        root=APPS_AGENTS,
        allowlist=APPS_AGENTS_ALLOWLIST,
        service_name="apps/agents/",
    )


def test_apps_worker_only_allowed_server_imports() -> None:
    _assert_only_allowed_server_imports(
        root=APPS_WORKER,
        allowlist=APPS_WORKER_ALLOWLIST,
        service_name="apps/worker/",
    )


def test_plugins_agents_imports_no_server_modules() -> None:
    """plugins/agents/ has NO allowlist — agent plugin code must never
    reach into the API service. The plugin SDK + storage ports are the
    only legitimate dependencies for agent plugins.
    """
    violations: list[tuple[Path, int, str]] = []
    for py in _walk_python_files(PLUGINS_AGENTS):
        for lineno, dotted in _collect_server_imports(py):
            violations.append((py.relative_to(REPO_ROOT), lineno, dotted))
    assert not violations, (
        "plugins/agents/ imported server.* modules:\n"
        + "\n".join(f"  - {path}:{ln} imports {dotted}" for path, ln, dotted in violations)
        + "\n\nAgent plugins consume packages/py/plugin_sdk + packages/py/storage. "
        "There is NO allowlist here — every violation is a contract bug."
    )


def test_boundary_uses_ast_not_regex() -> None:
    """Sanity check on the test file itself — ``import ast`` must be
    present so a future refactor doesn't silently downgrade the check
    to regex (which misses aliases + multiline imports).
    """
    self_text = Path(__file__).read_text()
    assert "import ast" in self_text, "boundary test must walk the AST, not regex"
