# storage

Ports + implementations for everything that crosses the application/DB
boundary.

## Layout

```
storage/
├── ports.py           Protocol contracts (the swappable seam)
└── timescale/         v1 TimescaleDB implementations
    ├── __init__.py    re-exports the public surface of every impl module
    └── runs.py        TimescaleRunRepository — pipeline_runs ledger
```

## Adding a new port

1. Define the Protocol in `ports.py` with method signatures matching
   what the consumer needs. Methods take a session argument, return
   frozen dataclasses or basic types — never SQLAlchemy Row objects.
2. Add a concrete class in `timescale/<concern>.py`. The class is
   stateless — every method takes the session.
3. Re-export the class + the dataclasses + a `default_<concern>`
   instance from `timescale/__init__.py`.
4. (Optional) Add module-level convenience functions delegating to the
   default instance, for v1.x consumers that want the simpler call
   shape.
5. Migrate consumers one at a time. The Protocol can be injected via
   constructor or via `app.state.<port>_repo` — see
   `apps/api/server/api/insights.py::_record_trigger_run` for the
   pattern (uses `app.state.session_factory` today; full Protocol
   injection lands in Phase 5B+).

## What lives here vs. what doesn't

| Concern | Today | Future |
|---------|-------|--------|
| Pipeline runs ledger | ✅ `storage/timescale/runs.py` | — |
| Apple Health ingest | `apps/api/server/ingestion/storage.IngestStorage` | Migrate to `storage/timescale/ingest.py` (Phase 5B) |
| Analysis runs/findings/insights | `apps/api/server/api/insights.py` raw SQL | Migrate to `storage/timescale/insights.py` (Phase 5B) |
| Measurements (heart_rate, hrv, ...) | `apps/api/server/ingestion/handlers.py` raw SQL | Migrate to `storage/timescale/measurements.py` (Phase 5C) |
| Time-series queries (Grafana-shaped) | spread across handlers | `storage/timescale/series.py` (Phase 5C) |
| Agent run ledger | not built yet | `storage/timescale/agents.py` (Phase 7) |

## End state (Phase 5D)

```bash
rg "import sqlalchemy" packages/py/ apps/
# only matches inside packages/py/storage/timescale/
```

Until then, the existing direct-SQL call sites continue to work; this
package is the migration target, not a hard requirement.
