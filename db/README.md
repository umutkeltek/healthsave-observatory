# db/

Database schema and migrations. TimescaleDB (PostgreSQL extension)
is the v1 implementation; storage ports in `packages/py/storage/`
keep the rest of the codebase from depending on the SQL shape.

| path | purpose | populated |
|------|---------|-----------|
| `schema.sql` | Bootstrap schema applied by Compose at first startup | Phase 1A |
| `migrations/` | Incremental schema changes (additive only — see project CLAUDE.md) | Phase 1A |

Rule: migrations are additive. Don't drop tables; don't rename columns
in-place. The same v1 invariant the iOS app depends on for ingest
applies to the schema itself.
