"""SQLAlchemy-import invariant: enforce the storage boundary.

The Phase 5 storage ports framework has one architectural goal:
sqlalchemy imports are confined to ``packages/py/storage/`` — the
``ports.py`` Protocols use ``AsyncSession`` for typing; everything
in ``timescale/`` runs the actual SQL. Nothing else in
``packages/py/`` or ``apps/`` should reach for sqlalchemy directly.
This test guards that invariant — *forward-only*. Each file
currently allowed to import sqlalchemy outside the storage zone is
named explicitly; new violations fail CI.

The allowlist categorizes each entry by why it's there and what
phase will retire it. As we migrate code into storage/, we delete
entries from this list and the test catches any backsliding.

The test fails in two directions:
1. A file in the allowlist no longer exists or no longer imports
   sqlalchemy → tighten the allowlist (drop the entry).
2. A new file outside the storage zone imports sqlalchemy without
   being in the allowlist → migrate it into storage/ or add it
   here with a deferral note.

Neither case is allowed to slip silently. Both are CI failures.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (REPO_ROOT / "packages" / "py", REPO_ROOT / "apps")
# The whole storage package is the allowed zone — `ports.py` uses
# `AsyncSession` for Protocol typing; `timescale/` runs the SQL.
STORAGE_ZONE = REPO_ROOT / "packages" / "py" / "storage"

# Matches both `import sqlalchemy` and `from sqlalchemy[.foo] import …`
# at the start of a line.
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+sqlalchemy(?:\.|\s|$)", re.MULTILINE)


# ---- Allowlist ---------------------------------------------------
#
# Each entry is a path relative to REPO_ROOT, paired with the reason
# it exists. The reason names the phase that retires the entry, OR
# "stays" for entries that are correct long-term (engine/session
# bootstrap and AsyncSession typing in route signatures).
#
# Goal: the list shrinks toward "stays"-only. Entries flagged for
# migration are technical-debt markers with a phase number attached.
ALLOWLIST: dict[str, str] = {
    # --- Stays — long-term correct outside storage/timescale/ ---
    "apps/api/server/db/session.py": (
        "stays — engine/session bootstrap (FastAPI lifecycle, not data access)"
    ),
    "apps/worker/worker/listener.py": (
        "stays — AsyncSessionFactory typing for the APScheduler listener. "
        "Phase 5G lifted the inline _lookup_run_id SQL into "
        "storage.timescale.runs.lookup_id_by_idempotency_key; the only "
        "remaining sqlalchemy import here is the `async_sessionmaker` "
        "type hint."
    ),
    # AsyncSession typing in route handler signatures (Depends pattern).
    # These do not run raw SQL — they pass the session to repositories.
    "apps/api/server/api/ingest.py": (
        "stays — AsyncSession typing for Depends(); repository calls only"
    ),
    "apps/api/server/api/insights.py": (
        "stays — AsyncSession typing for Depends(); repository calls only"
    ),
    "apps/api/server/api/v2_metrics.py": (
        "stays — v2 read API. AsyncSession typing for Depends(); the SQL lives in "
        "storage.timescale.observations (CanonicalObservationRepository), not the route."
    ),
    "apps/api/server/api/v2_insights.py": (
        "stays — v2 insights read/trigger API. AsyncSession typing for Depends(); the "
        "SQL lives in storage.timescale.briefings (fetch_correlations), not the route."
    ),
    "apps/api/server/api/v2_readiness.py": (
        "stays — v2 data-readiness API. AsyncSession typing for Depends(); the SQL "
        "lives in storage.timescale.analysis (fetch_canonical_coverage / "
        "fetch_canonical_sources), the grading is the pure analysis.statistical.gates."
    ),
    "apps/api/server/api/v2_agents.py": (
        "stays — Phase 7-E route. AsyncSession typing for Depends() + "
        "sqlalchemy.exc.IntegrityError catch to map FK violations on a "
        "missing proposal_id to a 404. All actual SQL stays in "
        "storage.timescale.agents (the Phase 7-B repository)."
    ),
    "apps/api/server/api/health_routes.py": (
        "stays — readiness probe runs SELECT 1; trivial enough to skip migration"
    ),
    "apps/api/server/api/status.py": (
        "stays — Apple Health status endpoint reads count(*) per metric table. "
        "Phase 5G decided NOT to migrate the SQL into storage/timescale/measurements.py: "
        "the route's silent-fallback semantics ({count:0} on any failure) are part of "
        "the iOS wire contract — wrapping behind a repository would either change the "
        "contract or duplicate the same try/except shape behind a layer of indirection. "
        "STATUS_QUERY_FAILURES{metric, exception} counter (added 5G-3) is the "
        "operator-side surface."
    ),
    # Phase 5F retired the four `packages/py/analysis/*` entries here:
    #   engine.py, statistical/aggregator.py, statistical/anomaly.py,
    #   statistical/trends.py — their SQL now lives in
    #   `packages/py/storage/timescale/analysis.py`. The originals are
    #   the analysis orchestrators; they reach the SQL via a lazy
    #   `_sql()` import. The allowlist is now "stays-only" — every
    #   remaining entry is long-term-correct outside the storage zone.
}


def _files_with_sqlalchemy_imports() -> set[str]:
    """All files under packages/py/ + apps/ that import sqlalchemy,
    relative to REPO_ROOT, excluding the storage zone."""
    out: set[str] = set()
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            # Skip files inside the allowed zone.
            try:
                path.relative_to(STORAGE_ZONE)
            except ValueError:
                pass
            else:
                continue
            text = path.read_text()
            if _IMPORT_RE.search(text):
                out.add(str(path.relative_to(REPO_ROOT)))
    return out


def test_no_unexpected_sqlalchemy_imports() -> None:
    """Every file outside storage/timescale/ that imports sqlalchemy
    must be in ALLOWLIST. New violations fail this test."""
    found = _files_with_sqlalchemy_imports()
    unexpected = found - ALLOWLIST.keys()
    assert not unexpected, (
        "sqlalchemy imports outside storage/timescale/ in unallowed files:\n"
        + "\n".join(f"  - {p}" for p in sorted(unexpected))
        + "\n\nMigrate the SQL into packages/py/storage/timescale/, or — if it's "
        "long-term correct outside the storage zone — add the path to ALLOWLIST "
        "in tests/contract/test_storage_invariant.py with a 'stays — <reason>' note."
    )


def test_allowlist_has_no_stale_entries() -> None:
    """Every ALLOWLIST entry must still exist + still import sqlalchemy.

    When a phase migrates a file's SQL into storage/, the file either
    no longer exists or no longer imports sqlalchemy. In both cases the
    allowlist entry must be deleted — keeping it around hides the win
    and lets a new violation slip in under the same name.
    """
    found = _files_with_sqlalchemy_imports()
    stale = ALLOWLIST.keys() - found
    assert not stale, (
        "ALLOWLIST contains stale entries (file gone or no longer imports sqlalchemy):\n"
        + "\n".join(f"  - {p}" for p in sorted(stale))
        + "\n\nDelete the entry from tests/contract/test_storage_invariant.py."
    )


def test_storage_timescale_baseline() -> None:
    """Sanity: the timescale subpackage has at least the modules we
    expect. Not strictly an invariant — just a smoke check that the
    test isn't accidentally pointing at an empty directory and
    trivially passing. Phase 5A/B/C established four Timescale impls.
    """
    timescale = STORAGE_ZONE / "timescale"
    expected_modules = {
        "runs.py",
        "briefings.py",
        "ingest.py",
        "measurements.py",
        "analysis.py",
    }
    actual = {p.name for p in timescale.iterdir() if p.suffix == ".py"}
    missing = expected_modules - actual
    assert not missing, f"Expected timescale modules missing: {missing}"
