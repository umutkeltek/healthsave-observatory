# @hdh/web - HealthSave Observatory

The default user-facing web surface for HealthSave Observatory. It reads the v2
API, summarizes what changed against the user's own baseline, shows provenance,
and keeps privacy and egress state visible. Grafana remains bundled for raw
SQL-backed dashboards and builder workflows.

## Run

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev # http://localhost:4173
```

Point `API_BASE` at a running HealthSave Observatory API. Set `API_KEY` when the
API requires one. Server components fetch directly; the `/api/*` rewrite in
`next.config.mjs` covers client-side fetches.

## Status

The app is part of the default `docker compose` stack as service `web` on
`http://localhost:4173`; `WEB_BIND` controls the bind address. Remote deploys
publish it through the VM web port, currently `18090` in the deploy runbook.

Current surfaces: Today, Findings, Data, Sources, Library, Integrations,
Privacy, Intelligence, Settings, Compare, Relationships, Experiments, and Demo.
Empty, no-data, and backend-unreachable states are handled.

Next product work should keep the same boundary: Observatory web explains
baseline, findings, provenance, source health, and egress state. Grafana handles
raw dashboarding.

Visual verification needs the full stack running: API, TimescaleDB, and some
ingested data. CI verifies build and typecheck level.
