/**
 * @hdh/api-client — generated TypeScript types for v1 + v2.
 *
 * Two namespaces:
 *
 *   import type { paths as V1Paths } from "@hdh/api-client/v1";
 *   import type { Measurement, AgentRun } from "@hdh/api-client/v2";
 *
 * v1 is the frozen HealthSave iOS contract. v2 is the canonical type
 * surface for the agent-platform direction. The two never cross —
 * imports from `./v1` are wire-frozen, imports from `./v2` are the
 * source of truth Pydantic models, generated.
 *
 * Regenerate either side via `make regen-ts-client`. CI fails the
 * build if regen produces an uncommitted diff.
 */

export type * as V1 from "./v1.js";
export type * from "./v2.js";
