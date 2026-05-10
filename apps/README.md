# apps/

Deployable units. Each subdirectory is a thing you can run:

| dir | role | status |
|-----|------|--------|
| `api/` | FastAPI HTTP surface (the v1 ingest + insights server) | populated in Phase 1B |
| `worker/` | Schedulers, pipeline runs, deterministic jobs | populated in Phase 4 (split out of `api/`) |
| `agents/` | Long-lived autonomous agents (anomaly watcher, experiment runner) | populated in Phase 7 |
| `web/` | Primary product UI (Next.js 15 dashboard) | populated in Phase 8 |

Rule: anything in `apps/` should be runnable as a process via Docker
Compose. Shared logic goes in `packages/`, not here.
