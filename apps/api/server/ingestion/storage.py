"""Backwards-compat shim — the real types now live in ``storage``.

Phase 5C moved this module's content to:
- ``storage.ports.IngestStorage`` (Protocol)
- ``storage.ports.AuditLog`` (Protocol)
- ``storage.timescale.ingest.PostgresIngestStorage`` (impl)
- ``storage.timescale.ingest.PostgresAuditLog`` (impl)
- ``storage.timescale.ingest.default_storage`` / ``default_audit_log``

Existing callers (registry, route, tests) keep their import path
through this shim. New code should import from ``storage`` directly.
The shim disappears in Phase 5D (or whenever the last caller migrates).
"""

from __future__ import annotations

from storage.ports import AuditLog, IngestStorage
from storage.timescale.ingest import (
    PostgresAuditLog,
    PostgresIngestStorage,
    default_audit_log,
    default_storage,
)

__all__ = [
    "AuditLog",
    "IngestStorage",
    "PostgresAuditLog",
    "PostgresIngestStorage",
    "default_audit_log",
    "default_storage",
]
