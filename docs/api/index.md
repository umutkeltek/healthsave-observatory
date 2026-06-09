# API

HealthSave Observatory exposes two HTTP surfaces, and they are deliberately not the same kind of thing.

- **v1 ingest — frozen.** A tiny, byte-stable contract the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app depends on. Its shapes, field names, and status response are locked. New work never changes them.
- **v2 read/query — evolving.** Your private read API: typed JSON endpoints under `/api/v2/` that your own scripts, notebooks, and dashboards query. It is under active development and may change between releases.

This split is the whole point. The thing that pushes data *in* (the App Store binary) must never break, so it is frozen; the thing you read data *out* with is free to grow as the Observatory does.

## The two surfaces

| Surface | Prefix | Stability | Who calls it |
|---|---|---|---|
| **v1 ingest** | `/api/apple/*`, `/api/health` | Frozen — byte-stable | HealthSave iOS app, compatible third-party clients, importers |
| **v2 read/query** | `/api/v2/*` | Evolving — pre-stable | Your scripts, the Observatory web app, Home Assistant, (planned) `healthsave` CLI + MCP server |

The legacy `/api/insights/*` endpoints are also frozen (typed and locked alongside v1); their v2 equivalents under `/api/v2/insights/*` are the surface that continues to evolve.

- **[v1 Apple contract](v1-apple-contract.md)** — the frozen ingest wire contract and the "don't change shapes" rule.
- **[v2 read API](v2-read-api.md)** — the evolving read/query plane for your own tooling and agents.
- **[`API_REFERENCE.md`](../../API_REFERENCE.md)** — the payload-level reference: every endpoint, with request/response examples and who calls each one.

## Authentication

Auth is a single shared key sent as the **`X-API-Key`** header. Set it once with `API_KEY` in your `.env` (and in the HealthSave app). When set, every endpoint that returns health data requires the header; a missing or wrong key returns `401`.

The Observatory is **fail-closed by default**. If `API_KEY` is unset and you have not explicitly acknowledged running open, keyed endpoints return `503 auth_not_configured` rather than serving your data unauthenticated. To run open on a trusted local network for a demo, set `ALLOW_NO_AUTH=true`.

A few endpoints are intentionally **open** (no key), because they expose no health data: `/health`, `/api/health`, `/ready`, `/metrics`, `/api/v2/meta`, `/api/v2/setup/diagnostics`, and `/api/v2/metrics` (the static metric catalog). The Whoop webhook authenticates by HMAC signature, not `X-API-Key`.

## Base URL

The server is given the **base URL only** — clients append the paths themselves:

```
http://your-server-ip:8000
```

Run `./setup.sh doctor` to print the exact URL to paste into the HealthSave app under Settings → Server Sync. Don't expose plain HTTP to the internet; put it behind a reverse proxy and a long random `API_KEY` (see [Reverse proxy](../operations/reverse-proxy.md)).

## Licensing of the API surface

The contract definitions, the generated API client, and the plugin SDK (`contracts/`, the api-client, the Source/storage SDK) are **Apache-2.0**, so anything can speak the format. The product core that implements them is **source-available** under the Elastic License 2.0 — self-host freely, but not as a managed service for third parties. See [`LICENSING.md`](../../LICENSING.md) for the per-path map.
