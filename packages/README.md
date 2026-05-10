# packages/

Shared libraries. Multiple `apps/` and `plugins/` import from these.
Nothing in `packages/` is independently runnable.

| dir | language | role |
|-----|----------|------|
| `py/` | Python | canonical contracts, domain model, storage ports + adapters, plugin SDK, runtime, analysis |
| `ts/` | TypeScript | generated API client, generated Zod schemas, shared UI primitives |

Rule: `py/contracts/` is the single source of truth for every shape.
JSON Schema and TS types are *generated* from there in CI; never
hand-mirrored.
