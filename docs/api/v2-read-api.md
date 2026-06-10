# v2 read API (evolving)

The `/api/v2/` plane is **your private read API** — the agent-consumable JSON surface your own scripts, notebooks, and dashboards query locally, without handing your data to a third-party API vendor. It is what the Observatory web app reads today, and it is the contract the planned `healthsave` CLI and local MCP server will speak so your own AI agents can query your body data.

> **Status: evolving — not frozen.** Unlike the [v1 ingest contract](v1-apple-contract.md), the v2 read plane is under active development; request and response shapes may change between releases. Treat it as pre-stable and pin to a backend version when scripting against it.

This page is the orientation map. For payload-level request/response examples on every endpoint, see [`API_REFERENCE.md`](../../API_REFERENCE.md).

## Auth and versioning

Most v2 endpoints are **keyed** — send the `X-API-Key` header when `API_KEY` is set (see [API overview](index.md#authentication)). A few are **open** because they expose no health data: `/api/v2/meta`, `/api/v2/setup/diagnostics`, and `/api/v2/metrics` (the static catalog). The Whoop webhook authenticates by HMAC signature instead.

Check `GET /api/v2/meta` first — it reports the running backend's version axes (`api_contract`, `ontology`, `normalizer`, `fusion_policy`) so a client can detect contract drift before relying on a shape.

## Metrics and time series

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/metrics` | open | List available canonical metrics (static catalog; ids are dotted, e.g. `vital.heart_rate`) |
| `GET /api/v2/metrics/{metric_id}/series` | key | Time series for one metric (`range`, e.g. `7d`, or `start`/`end`) |
| `GET /api/v2/series` | key | Batch time series for many metrics (`ids=` comma list, max 24; unknown ids return per-item errors) |

The series endpoints return points tagged with `source_id`, `unit`, and optional `confidence` — the same contract the local LLM narrator consumes.

## Insights and readiness

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/insights/latest` | key | Latest daily-briefing + weekly-summary narratives |
| `GET /api/v2/insights/findings` | key | Structured findings from the statistical engine (the evidence behind a briefing) |
| `GET /api/v2/insights/correlations` | key | Recent cross-metric correlation findings |
| `POST /api/v2/insights/trigger` | key | Run a briefing / trend / analysis job on demand (body `{ "type": "daily" | "weekly" | "anomaly" }`) |
| `GET /api/v2/readiness` | key | Per-metric data sufficiency — is there enough history to run anomaly/trend analysis |

Findings are computed by a deterministic statistical engine; the local LLM only narrates them. See [How the AI analysis works](../operations/local-llm.md) for the two-brain split.

## Identity — Source / Device / Stream

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/sources` | key | Source integrations (the path data entered through) |
| `GET /api/v2/devices` | key | Distinct device emitters (derived from streams) |
| `GET /api/v2/streams` | key | Source-device streams with stable deterministic UUIDs |
| `GET /api/v2/streams/{stream_id}` | key | One stream (`404` if unknown) |

A *stream* is the join of "this device, via this integration" — the same band over HealthKit versus a direct poll is two streams. Stream UUIDs are stable, so Home Assistant and other consumers can key entities on them without fragmenting when you add devices.

## Experiments and agents

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET, POST /api/v2/experiments` | key | List / create n-of-1 self-experiments |
| `GET /api/v2/experiments/candidates` | key | Suggested experiments |
| `GET /api/v2/experiments/{experiment_id}` | key | One experiment |
| `POST /api/v2/experiments/{experiment_id}/analyze` | key | Analyze an experiment's result |
| `POST /api/v2/experiments/{experiment_id}/abandon` | key | Abandon an experiment |
| `GET /api/v2/agents/proposals` | key | Pending agent action proposals |
| `POST /api/v2/agents/proposals/{proposal_id}/decide` | key | Approve / reject a proposal |

The agents surface is human-in-the-loop by design: an agent proposes an action, a person decides.

## Sync receipts

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/sync/runs/latest` | key | Most recent sync-run summary |
| `GET /api/v2/sync/runs/{sync_run_id}` | key | Per-run delivery-receipt summary + per-metric breakdown |
| `GET /api/v2/sync/coverage` | key | Per-metric receipt-vs-destination freshness |
| `GET /api/v2/sync/anomalies` | key | Overlapping / concurrent sync-run detection |

These prove a sync reached the backend and separate delivery-receipt time from sample-window freshness — with honest accounting that never counts aggregation rollups or in-batch dedup as "rejected." Details in [`API.md`](../../API.md).

## Export

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/export/metrics` | key | List exportable metrics with counts + date ranges |
| `GET /api/v2/export` | key | Export one metric (or `all`) as JSON or CSV (`limit` clamped to 100k) |

## Privacy and egress

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v2/privacy` | key | The egress policy + audit: what derived data may leave the host |

This makes the trust boundary inspectable. By default `raw_observations_leave_host` is `false`, cloud egress is off, and on-device prompt redaction is on — the moat, made queryable.

## Webhooks

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v2/sources/whoop/webhook` | HMAC | Whoop push webhook; authenticity via `X-WHOOP-Signature` (not `X-API-Key`) |

## Planned: CLI and MCP

A `healthsave` CLI and a local MCP server are on the roadmap. Both will sit on top of this same v2 read API, with scoped read tokens, so your own agents can query your body data through the contract documented here rather than against the database directly. Until they ship, scripts call these endpoints over HTTP with the `X-API-Key` header. See [`API_REFERENCE.md`](../../API_REFERENCE.md) for payloads.
