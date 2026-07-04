# Observatory Web App

The Observatory web app is the insight-first web surface for HealthSave
Observatory. It is a Next.js app (`apps/web`) that reads the canonical health
record over the v2 API and shows what changed against your own baseline, not
just a wall of charts.

It is part of the default Docker Compose stack as service `web` on
`http://localhost:4173`. Grafana remains bundled as service `grafana` on
`http://localhost:3000` for power-user SQL-backed dashboards. See
[Web vs Grafana](web-vs-grafana.md) for the separation.

## What It Shows

Observatory is built around one question: what changed, compared with my own
baseline, and where did it come from?

- **Today vs baseline.** The Today surface puts recovery, last sync, top
  changes, and data health in the first product layer.
- **What changed.** Findings and Weekly Brief surfaces frame changes as
  evidence-linked findings instead of raw rows.
- **Source coverage and provenance.** Sources shows where readings came from,
  which hardware produced them, and how fresh each stream is.
- **Privacy and egress.** Privacy and Intelligence expose the trust boundary:
  default-deny egress, raw rows staying on host, and cloud narration only by
  consent.

Pages today: Today, Findings, Data, Sources, Library, Integrations, Privacy,
Intelligence, Settings, Compare, Relationships, Experiments, and Demo. Empty,
no-data, and backend-unreachable states are handled so a fresh install degrades
gracefully instead of erroring.

Everything is driven by the v2 read API, including `/api/v2/metrics` and
`/api/v2/metrics/{id}/series`, the same contract the local LLM narrator
consumes. See [Findings & Body Briefs](findings-and-body-briefs.md) for how
findings are computed and narrated.

## Run It

For normal local use, run the stack through the CLI:

```bash
./healthsave setup basic
./healthsave doctor
```

Open:

- Observatory web: `http://localhost:4173`
- Grafana: `http://localhost:3000`

For frontend development only, run the web app manually against an already
running API:

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev
```

Point `API_BASE` at the running API, for example
`http://your-server-ip:8000` if the backend lives on another host. Set
`API_KEY` when the API requires one. Server components fetch directly; the
`/api/*` rewrite in `next.config.mjs` covers client-side fetches.

## Maturity

In active development, but already part of the default stack. Card surfaces,
source provenance, privacy egress posture, intelligence settings, the baseline
ribbon, and empty/unreachable states exist today, all driven by the v2 read API.
Still ahead: deeper Body Brief scheduling, richer conflict/divergence detection,
and more source/destination verticals.

Visual verification needs the full stack running: API, TimescaleDB, and some
ingested data. CI verifies app build and typecheck level. For the broader plan,
see the Roadmap in the project [README](../../README.md).
