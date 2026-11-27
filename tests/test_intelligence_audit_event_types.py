"""The audit allowlist in Python and the CHECK constraint in SQL agree.

``narrator_failover`` was added to the repository allowlist without a
migration, so every failover audit insert hit the CHECK and aborted the
briefing's transaction on PostgreSQL. This pins the two lists together: the
newest migration that defines the ``event_type`` check must allow exactly the
types the repository writes.
"""

from __future__ import annotations

import re
from pathlib import Path

from storage.timescale.intelligence import _AUDIT_EVENT_TYPES

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
_CHECK = re.compile(r"event_type\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def _latest_audit_event_type_check() -> tuple[str, set[str]]:
    latest: tuple[str, set[str]] | None = None
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = path.read_text()
        if "intelligence_audit_events" not in sql:
            continue
        for match in _CHECK.finditer(sql):
            latest = (path.name, set(re.findall(r"'([^']+)'", match.group(1))))
    assert latest is not None, "no migration defines the intelligence_audit_events check"
    return latest


def test_every_audit_event_type_the_repository_writes_is_allowed_by_the_database() -> None:
    migration, allowed = _latest_audit_event_type_check()
    assert set(_AUDIT_EVENT_TYPES) == allowed, (
        f"{migration} allows {sorted(allowed)}; the repository writes "
        f"{sorted(_AUDIT_EVENT_TYPES)}. Add a migration that widens the CHECK."
    )
