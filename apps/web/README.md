# @hdh/web — HealthSave dashboard

The standalone, insight-first dashboard for datahub v2 — the eventual
replacement for Grafana. Reads the v2 API (`/api/v2/metrics`,
`/api/v2/metrics/{id}/series`), the same contract the local LLM narrator will
consume.

## Run

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev   # http://localhost:4173
```

Point `API_BASE` at a running datahub API. Server components fetch it directly;
the `/api/*` rewrite (next.config.mjs) covers any client-side fetch.

## Status

Walking skeleton: an insight-first Heart Rate card (latest + trend + sparkline)
and a Sleep Stages hypnogram, both driven live by the v2 read API. Empty/no-data
and backend-unreachable states are handled. Next: design-system polish, more
verticals, and the AI narration cards once the local LLM layer lands.

> Visual verification (Interceptor) requires the full stack running (API +
> TimescaleDB + some ingested data). This commit is verified at the
> build/typecheck level only.
