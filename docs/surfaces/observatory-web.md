# Observatory Web App

The Observatory web app is the insight-first web surface for HealthSave Observatory. It is a Next.js app (`apps/web`) that reads the canonical health record over the v2 API and shows what changed against your own baseline, not just a wall of charts.

It is part of the default Docker Compose stack today as service `web` on `http://localhost:4173`. Grafana is still bundled as service `grafana` on `http://localhost:3000` for power-user SQL-backed dashboards. See [Web vs Grafana](web-vs-grafana.md) for the separation.

## What It Shows

Observatory is built around one question: what changed, compared with my own baseline, and where did it come from?

- **Today vs baseline.** Today / Recovery hero and Baseline Ribbon put the current day next to a personal rolling baseline.
- **What changed.** Heart Rate and Sleep cards surface recent movement and deviations; Evidence, Experiments, Readiness, and Weekly Brief cards frame the day as findings rather than rows.
- **Source coverage provenance.** Every observation is source-tagged in the canonical record, so Observatory can show completeness and where a number came from.
- **Privacy surface.** Privacy pages expose the trust boundary the rest of the stack enforces: default-deny egress and raw rows staying on host.

Pages today: home, evidence, experiments, privacy, data, and demo. Empty, no-data, and backend-unreachable states are handled so a fresh install degrades gracefully instead of erroring.

Everything is driven by the v2 read API, including `/api/v2/metrics` and `/api/v2/metrics/{id}/series`, the same contract the local LLM narrator consumes. See [Findings & Body Briefs](findings-and-body-briefs.md) for how findings are computed and narrated.

## Run It

For normal local use, run the stack through the CLI:

```bash
./healthsave setup basic
./healthsave doctor
```

Open:

- Observatory web: `http://localhost:4173`
- Grafana: `http://localhost:3000`

For frontend development only, run the web app manually against an already running API:

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev
```

Point `API_BASE` at the running API, for example `http://your-server-ip:8000` if the backend lives on another host. Server components fetch directly; the `/api/*` rewrite in `next.config.mjs` covers client-side fetches.

## Maturity

Pre-release, in active development. Card surfaces, the baseline ribbon, and empty/unreachable states exist today, all driven by the v2 read API. Still ahead: design-system polish, more verticals, and wiring AI narration cards to the local LLM layer so the Weekly Brief card renders a real [Body Brief](findings-and-body-briefs.md).

Visual verification needs the full stack running: API, TimescaleDB, and some ingested data. CI verifies app build and typecheck level. For the broader plan, see the Roadmap in the project [`README.md`](../../README.md).
