# contracts (v2 canonical)

Single source of truth for v2 wire shapes. Pydantic in Python,
generated everywhere else.

## What lives here

| File | Contents |
|------|----------|
| `_base.py` | `V2Model`, `WithOwnership`, `Provenance`, identifier aliases, `DEFAULT_OWNER_ID`/`DEFAULT_WORKSPACE_ID` sentinels |
| `data.py` | `Measurement`, `Source`, `Device`, `RawSourcePayload`, `NormalizedMeasurement`, `IngestionRun`, `IngestionError`, `SourceCapability` |
| `agents.py` | `AgentSpec`, `AgentRun`, `Observation`, `ActionProposal`, `ActionDecision`, `ActionExecution`, `AgentEvent`, `AgentArtifact` |
| `narrative.py` | `NarrativeArtifact`, `Insight`, `Claim`, `EvidenceRef`, `Uncertainty`, `SuggestedAction` |
| `ui.py` | `ChartSpec`, `SeriesResponse`, `Annotation`, `NarrativeCard` |
| `plugins.py` | `PluginManifest`, `PluginPermissions`, `PluginCapability` |

`__init__.py` re-exports everything for `from contracts import X` and
defines `ALL_MODELS` — the canonical list driving the schema export
and the JSON-Schema-serializability test.

## Hard rules

1. **`contracts/` never imports `compat_v1/`.** Enforced by
   `tests/contract/v2/test_v2_invariants.py`. v1 and v2 coexist
   forever; they never cross-reference.
2. **Every record-of-user-data extends `WithOwnership`.** This adds
   `owner_id` + `workspace_id` from day one — single-user installs
   default to the sentinel UUIDs, multi-user / federated setups
   later only need to populate different ids.
3. **`extra="forbid"` on every model.** Unknown fields fail loudly
   at validation; canonical contracts don't accept silent drift.
4. **Frameworks compete to implement the agent contract.** The
   `Agent*` types here ARE the contract. LangGraph, Mastra, Burr,
   etc. become *executors* against this shape; none of them define
   the boundary.

## Regenerating JSON Schema

```bash
make regen-v2-schemas
```

Same Docker-pinned approach as the v1 OpenAPI lock. Outputs land in
`contracts/json-schema/*.json`, one file per public type, sorted by
type name. CI fails the build if regen produces an uncommitted diff.

## Cross-reference

- `compat_v1/` — frozen v1 wire shapes (HealthSave iOS today).
- `contracts/V1.md` — v1 contract surface doc.
- `tests/contract/v2/` — invariants + per-type sanity tests.
