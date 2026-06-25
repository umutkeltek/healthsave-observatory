# Overview

HealthSave Observatory is a self-hosted private body observatory. It brings health data from multiple sources into one canonical record you own, shows what changed against your own baseline, computes evidence-linked findings, and lets you route/query the data from your own tools.

It runs on your hardware: laptop, NUC, Mac mini, NAS, or homelab VM. Raw observations stay on your host unless you explicitly enable an egress route.

## Product Layers

| Layer | What It Does | Required? |
|---|---|---|
| HealthSave iOS app | Reads Apple Health and pushes batches to the backend | Required for Apple Health sync |
| Observatory API | FastAPI ingest/read API and compatibility contract | Required for self-hosting |
| TimescaleDB | Canonical health record | Required |
| Worker | Findings, summaries, recovery jobs | Required in default stack |
| Observatory web | Primary insight-first surface | Bundled |
| Grafana | SQL-backed power-user dashboards | Bundled |
| Local AI / Ollama | Narrates already-computed findings | Optional |
| Home Assistant / MQTT | Publishes selected signals to Home Assistant | Optional |
| Agents | Future/local automation surface | Optional |

## Data Flow

There are two ingest lanes:

- **Apple Health and compatible importers:** `POST /api/apple/batch`, the frozen v1 compatibility contract used by the HealthSave iOS app.
- **Native apps, generic sources, webhooks:** planned `/api/v2/ingest/batch`, for source-agnostic clients such as Android Health Connect and HMAC-signed webhooks.

Both lanes normalize into the same canonical record.

```text
Apple Health -> HealthSave iOS app -> /api/apple/batch
Whoop/Amazfit plugins -------------> Observatory API
Garmin/Samsung importers ----------> Observatory API
                                      |
                                      v
                                TimescaleDB
                                      |
        ---------------------------------------------------------
        |                 |                  |                  |
        v                 v                  v                  v
  Observatory web      Grafana            Worker           MQTT/Home Assistant
  v2 read API          SQL dashboards      findings         optional route
```

## What You Get

- **Universal capture.** Apple Health today via the iOS app; early Whoop/Amazfit plugins and Garmin/Samsung importers; planned Android Health Connect and generic webhooks.
- **One record you own.** Source / Device / Stream identity keeps integrations, physical devices, and metric streams distinct.
- **A private Observatory.** Observatory web shows today vs personal baseline, what changed, and where numbers came from.
- **Power-user dashboards.** Grafana stays bundled for raw SQL-backed exploration and custom dashboards.
- **Evidence-linked findings.** The statistical engine computes findings; local LLM only narrates them.
- **Your own private API.** Scripts, notebooks, dashboards, and future agents can read through the v2 API.
- **Optional routes.** Home Assistant, MQTT, webhooks, and exports can consume selected signals under explicit policy.

## Web vs Grafana

Observatory web is the product surface. It should answer: what changed, compared with my own baseline, and why?

Grafana is the power-user surface. It should answer: what raw chart or SQL-backed dashboard do I want to build?

See [Web vs Grafana](surfaces/web-vs-grafana.md).

## Local vs Self-Hosted

The iOS app works on its own: on-device Dashboard, Trends, and Export to CSV/JSON/PDF do not require the backend.

Install Observatory when you want a longitudinal record you own, web dashboards, findings, routes, local AI narration, or a private API.

## Get Started

1. [Zero To Ready](zero-to-ready.md) - clean-machine path from clone to running stack.
2. [Connect HealthSave](connect-healthsave.md) - pair the iOS app and sync.
3. [Observatory web](surfaces/observatory-web.md) - use the primary web surface.
4. [Home Assistant & MQTT](integrations/home-assistant.md) - optional automation route.

## What This Is Not

- Not a cloud service.
- Not a replacement for Apple Health.
- Not a medical device.
- Not a hidden data collector.

It is a private system for owning, understanding, and building on your own health data.
