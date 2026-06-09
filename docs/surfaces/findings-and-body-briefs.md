# Findings & Body Briefs

HealthSave Observatory does not "feed everything to a cloud model and hope." It computes findings deterministically, then uses a local language model only to put them into plain words. This page explains the two-brain system, what ships today, what's in progress, and exactly where the privacy boundary sits.

There is no "AI coach" here. A deterministic statistical engine decides what is interesting; the LLM only narrates it.

## The two-brain system

The analysis runs as two separate brains with a one-way handoff:

- **Brain 1 — the statistical engine.** A small Python module that runs on a schedule, reads your time-series data (heart rate, HRV, sleep, and so on), computes baselines and trends, and flags anything statistically interesting — a 3-day HRV decline, a heart-rate-recovery anomaly, a sleep-stage shift. It produces **structured findings, not prose**. This is pure math: deterministic and auditable.
- **Brain 2 — the narrative LLM.** A local [Ollama](../operations/local-llm.md) model takes those findings and rewrites them as a short, readable briefing. It only sees the flagged findings it needs, never raw rows it doesn't, and turns them into sentences like *"Your HRV has dropped three days running while sleep efficiency stayed flat — this often shows up before a stress spike."*

The split is deliberate: the math stays deterministic and auditable; the LLM only handles the part where natural language actually helps. No cloud, no per-query cost, no data leaving your network on the local path.

## What ships today

A two-brain daily briefing ships today. The MVP includes:

- Daily HR / HRV summary
- HR / HRV anomaly detection against your rolling baseline
- HR / HRV trend detection over a configurable 30-day window
- Workout recovery hints when HR or HRV deviates from baseline
- Weekly summaries and cross-metric correlation analysis

These are exposed over read and trigger endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/insights/latest` | GET | Most recent rendered briefing |
| `/api/insights/anomalies` | GET | Recent anomaly findings (filter by `since`, `severity`) |
| `/api/insights/trends` | GET | Recent HR / HRV trend findings (filter by `period=30d`) |
| `/api/insights/trigger` | POST | Run an analysis pass now |

### Your first insight

Briefings need at least one full day of heart-rate data to say anything useful. Once you've synced from the HealthSave iOS app at least once, you have two ways to see your first briefing:

**Option A — wait for the daily cron.** The analysis worker ticks once a day (default 7am local) and writes a fresh briefing. Easiest, but slow right after install.

**Option B — trigger one now.**

```bash
curl -X POST http://your-server-ip:8000/api/insights/trigger
```

(Add `-H "X-API-Key: your-key"` if you set an `API_KEY` in `.env`.)

The response includes a run ID; poll `GET /api/insights/latest` for the rendered briefing once the run completes (usually 5–30 seconds depending on model size). If the briefing comes back empty or terse, it usually means there isn't enough data yet — sync another day and trigger again.

## What's in progress

The daily briefing is the shipped slice of a larger loop. Still being built:

- **The weekly Body Brief.** The productized weekly narrative — the thing meant to bring you back week over week — built on the same findings pipeline. It is in progress, not yet shipped.
- **A first-class finding-card schema.** Each finding rendered as an evidence card: the **claim**, the **baseline window** it was measured against, the **effect size**, a **confidence** level, and — importantly — **what it cannot conclude**. This makes every narrated sentence traceable back to deterministic math.

Also on the roadmap (not yet included): goal-tracking, anomaly alerting via Home Assistant, and multi-person households.

## Privacy: where the boundary sits

By default, nothing leaves your network. The local Ollama path is never redacted, because that data never left.

Going cloud is **opt-in, and redacted**. If you deliberately point Brain 2 at a cloud model (`allow_cloud_egress: true`), a default-deny egress gate still guarantees raw rows never leave — only derived findings and the assembled prompt cross the boundary. That prompt is first scrubbed on-device of identifiers (emails, phone numbers, opaque IDs, names) via `redact_cloud_prompts`, which is on by default.

In short:

- **Local (Ollama) path:** raw rows stay on your host; nothing crosses the boundary; no redaction needed.
- **Cloud path (opt-in):** only derived, on-device-redacted findings and the scrubbed prompt cross — never raw observations.

This is the same trust boundary the [Observatory web app](observatory-web.md) surfaces on its Privacy page. See the [local LLM operations guide](../operations/local-llm.md) for model selection and the project [`README.md`](../../README.md) for the full egress description.
