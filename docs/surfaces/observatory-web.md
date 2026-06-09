# Observatory Web App

The Observatory is the standalone, insight-first web surface for HealthSave Observatory. It is a Next.js app (`apps/web`) that reads your canonical health record over the v2 API and shows you what changed against your own baseline — not just a wall of charts. This is the **pre-release primary surface**: the direction of the project, runnable manually today, with Grafana remaining the bundled default until the web app lands in the standard Docker Compose stack.

## What it shows

The Observatory is built around one question: *what changed, compared to my own baseline, and where did it come from?* Rather than a raw metric explorer, it leads with interpretation.

- **Today vs your baseline.** A Today / Recovery hero and a Baseline Ribbon put the current day next to your personal rolling baseline, so a number reads as "normal for you" or "off" at a glance.
- **What changed.** Heart Rate and Sleep cards surface recent movement and deviations, plus Evidence, Experiments, Readiness, and Weekly Brief cards that frame the day in terms of findings rather than rows.
- **Source coverage and provenance.** Because every observation is source-tagged in the canonical record, the Observatory can show how complete your data is and where each number came from — useful when two devices disagree about the same night.
- **Privacy surface.** A Privacy card and a dedicated privacy page expose the trust boundary the rest of the stack enforces (default-deny egress; raw rows stay on your host).

Pages today: home, evidence, experiments, privacy, data, and a demo page. Empty / no-data and backend-unreachable states are handled, so a fresh install degrades gracefully instead of erroring.

Everything is driven by the v2 read API — `/api/v2/metrics` and `/api/v2/metrics/{id}/series` — the same contract the local LLM narrator consumes. See [Findings & Body Briefs](findings-and-body-briefs.md) for how those findings are computed and narrated.

## The pre-release primary surface

The Observatory web app is the direction of the project: an insight-first surface that replaces the chart-first Grafana experience for everyday use, and it can be run manually today. It is not yet part of the standard Docker Compose stack, so [Grafana](grafana.md) remains the bundled default — the supported dashboard you get out of the box — until the web app lands in that stack. You can run the Observatory manually alongside Grafana in the meantime.

## How to run it today

The Observatory is not yet part of the default `docker compose` stack, so you run it manually against a running HealthSave Observatory API:

```bash
cd apps/web
bun install
API_BASE=http://localhost:8000 bun run dev   # http://localhost:4173
```

Point `API_BASE` at a running API (use `http://your-server-ip:8000` if the backend lives on another host). Server components fetch it directly; the `/api/*` rewrite in `next.config.mjs` covers any client-side fetch.

## Maturity

**Pre-release, in active development.** The card surfaces, baseline ribbon, and empty / unreachable states exist today, all driven by the v2 read API. What's still ahead: design-system polish, more verticals, and wiring the AI narration cards to the local LLM layer so the Weekly Brief card renders a real [Body Brief](findings-and-body-briefs.md). Visual verification needs the full stack running (API + TimescaleDB + some ingested data); CI verifies the app at the build / typecheck level.

For the broader plan — Observatory as the default surface, the weekly Body Brief loop, and the agent surface — see the Roadmap in the project [`README.md`](../../README.md).
