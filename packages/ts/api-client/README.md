# @hdh/api-client

Generated TypeScript types for the Health Data Hub API.

## What lives here

| File | Source | What it is |
|------|--------|-----------|
| `src/v1.ts` | `contracts/openapi/v1.locked.json` | OpenAPI 3.1 → TS types via `openapi-typescript`. v1 wire contract — frozen, HealthSave iOS depends on it. |
| `src/v2.ts` | `contracts/json-schema/_bundle.json` | Bundled Pydantic schemas → TS types via `json-schema-to-typescript`. v2 canonical types. |
| `src/index.ts` | hand-written | Re-exports — `V1` namespace + flat v2. |

## Regen

```bash
make regen-ts-client      # writes src/v1.ts and src/v2.ts
make check-ts-client      # CI-style drift check
```

The Python sources of truth (OpenAPI lock + JSON Schema bundle) are
themselves generated — if you change a contract, the chain is:

```
Pydantic source → make regen-v2-schemas → contracts/json-schema/*
                                       → make regen-ts-client → src/v2.ts
```

CI gates each step independently. A change at any layer that doesn't
flow through to the committed artifacts fails the build with a clear
"regenerate this" message.

## Direct use

```ts
import type { Measurement, AgentRun, NarrativeArtifact } from "@hdh/api-client";
import type { V1 } from "@hdh/api-client";

type IngestPayload = V1["paths"]["/api/apple/batch"]["post"]["requestBody"];
```

The runtime fetch layer (TanStack Query, openapi-fetch, plain
`fetch`, etc.) lives in `apps/web/`, not here. This package is
types-only.
