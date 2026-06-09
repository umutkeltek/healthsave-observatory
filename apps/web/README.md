# @hdh/web — HealthSave dashboard

The standalone, insight-first dashboard for HealthSave Observatory v2 — the eventual
replacement for Grafana. Reads the v2 API (`/api/v2/metrics`,
`/api/v2/metrics/{id}/series`), the same contract the local LLM narrator will
consume.

## Run

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev   # http://localhost:4173
```

Point `API_BASE` at a running HealthSave Observatory API. Server components fetch it directly;
the `/api/*` rewrite (next.config.mjs) covers any client-side fetch.

## Status

**Pre-release.** This dashboard is in active development and is **not part of the
default `docker compose` stack yet** — run it manually (see Run above). It's the
eventual insight-first replacement for Grafana; until it lands, Grafana stays the
supported visualization surface.

What's already here, all driven by the v2 read API: a Today/Recovery hero and a
Baseline Ribbon, Heart Rate and Sleep cards, plus Evidence, Experiments,
Privacy, Readiness, and Weekly Brief cards — across the home, evidence,
experiments, privacy, data, and demo pages. Empty/no-data and
backend-unreachable states are handled. Next: design-system polish, more
verticals, and wiring the AI narration cards to the local LLM layer.

> Visual verification (Interceptor) requires the full stack running (API +
> TimescaleDB + some ingested data); CI verifies it at the build/typecheck level.
