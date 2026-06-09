# HealthSave Observatory

[![CI](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml)
[![License: Elastic 2.0](https://img.shields.io/badge/License-Elastic--2.0-005571.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515.svg?logo=postgresql&logoColor=white)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20LLM-000000.svg)](https://ollama.com/)
[![Download on the App Store](https://img.shields.io/badge/Download-App%20Store-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/app/id6759843047)

> **Your whole body, in one place you own — and it actually tells you something.**
> HealthSave Observatory is a **self-hosted private body observatory**. It captures your health data from *any* device, builds a longitudinal record you own, explains what's changing with evidence-linked findings and **Body Briefs**, and exposes a private API your own scripts and tools can query — with **raw data that never leaves your hardware unless you choose to send it**.

New here? Start with the [overview](docs/overview.md) or jump to the [quick start](docs/quick-start.md).

## Status at a glance

| Area | Today | Next |
|---|---|---|
| **Capture** | Apple Health (HealthSave iOS), early Whoop/Amazfit plugins, Garmin/Samsung importers | Android Health Connect, generic webhook ingest |
| **Surface** | Grafana bundled today; web Observatory being wired in | web Observatory as the default surface |
| **Findings** | daily briefing / anomaly / trend analysis | weekly Body Brief + evidence-card schema |
| **Agent surface** | typed `/api/v2` read API | private CLI + local MCP server |
| **License** | source-available core (Elastic 2.0); Apache-2.0 protocol/SDK | premium / managed reserved |

## Why it exists

Your health data is scattered across silos you don't control — Apple Health here, Whoop's cloud there, Oura's app, your scale's app. Each one shows you a few charts and keeps the data. **HealthSave Observatory pulls all of it into one private place that's yours** — queryable, routable, and finally able to answer the questions that matter: *what changed, compared to my own baseline, where did it come from, and what should I look at next?*

It runs entirely on your hardware — a laptop, a NUC, a Mac mini, a Synology, a Proxmox VM. No cloud, no subscription, no one else reading your numbers. **Apple Health is the easiest way in, but it is not the boundary.**

The canonical ingest model is **source-agnostic** — Apple Health is the most polished on-ramp, not the boundary. Every source resolves to the same Source / Device / Stream identity:

| Source | How it connects | Status |
|---|---|---|
| **Apple Health** (Apple Watch, iPhone, and anything that writes to HealthKit) | Push, via the [HealthSave](https://apps.apple.com/app/id6759843047) iOS app | Shipped |
| **Whoop** | Direct poll plugin (OAuth to the Whoop API) | Shipped (early) |
| **Amazfit / Zepp** | Direct poll plugin | Shipped (early) |
| **Garmin Connect** | CLI importer | Shipped |
| **Samsung / Huawei Health** | CLI importer, via the Health Sync app | Shipped |
| **Android Health Connect** | Native capture into the generic ingest API | Planned |
| **Generic webhook / native API** | Any registered source posting canonical observations (HMAC-signed) | Planned |

Full detail per source: [docs/capture/index.md](docs/capture/index.md).

## Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/) installed and running. On Windows, run this inside WSL2 — `setup.sh` is a bash script.

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./setup.sh
```

`setup.sh` generates passwords, optionally sets up the local AI briefing (it detects your RAM + GPU and recommends a model), and brings the stack up. When it finishes, run `./setup.sh doctor` to confirm every service is healthy and print the exact URL to paste into the iOS app.

Full guide: [docs/quick-start.md](docs/quick-start.md) · [deployment](docs/operations/deployment.md) · [local LLM](docs/operations/local-llm.md).

## Connect HealthSave

The [**HealthSave** iOS app](https://apps.apple.com/app/id6759843047) is the Apple Health bridge:

1. Open HealthSave → Settings → Server Sync.
2. Set Server URL to `http://your-server-ip:8000` (iOS won't sync to `localhost`).
3. *(Optional)* Set your API key.
4. Tap **Sync New Data**.

Building another client? The batch endpoint is `POST /api/apple/batch`, a frozen v1 contract. Details: [docs/connect-healthsave.md](docs/connect-healthsave.md).

## What you get

- **Universal capture.** Apple Health (via [HealthSave](https://apps.apple.com/app/id6759843047)), early Whoop/Amazfit direct plugins, and Garmin/Samsung file importers today; Android Health Connect and generic webhooks planned — all normalized into one canonical, source-tagged record you can query with normal SQL.
- **One record you own.** Every source resolves to the same **Source / Device / Stream** identity, so dashboards and automations stay stable as you add devices.
- **A private Observatory dashboard.** *Today vs your personal baseline*, what changed, how complete the data is, and where each number came from. The web Observatory is the primary surface; Grafana ships as an optional power-user view.
- **Evidence-linked findings.** A deterministic statistical engine computes the findings; a local LLM only narrates them. A daily briefing ships today; the weekly **Body Brief** with full finding cards is in progress.
- **Your own private health API.** Query your history from your scripts, notebooks, and dashboards over a typed read API — locally, without handing your data to a third-party vendor. *(A `healthsave` CLI and a local MCP server are on the roadmap.)*
- **Route it anywhere (optional).** Home Assistant, MQTT, Grafana, webhooks, exports — your data piped to your tools, behind a policy you control.
- **A trust boundary you can audit.** Default-deny egress: raw observations never leave your host; cloud AI is opt-in and carries only derived, on-device-redacted findings.

## Architecture

```
CAPTURE (sources in)                        SURFACES & ROUTES (out)

HealthSave (Apple Health)         ┐         ┌─► Observatory web app  (primary)
Android Health Connect *          │         │
Whoop / Amazfit  (plugins)        ├─► FastAPI ─► TimescaleDB ─┼─► Grafana  (optional)
Garmin / Samsung (importers)      │  (8000)     (canonical    │
Generic webhook / native API *    ┘             observations) ├─► findings + Body Briefs
                                                              │     stats engine → local LLM (Ollama)
  v1 ingest  /api/apple/batch   (frozen contract)            │
  v2 ingest  /api/v2/ingest/... (planned)          *          ├─► Private API + CLI / your agents (/api/v2)
                                                              │
                                                              └─► Routes: Home Assistant · MQTT · webhook · export

                                                                   (* planned)
```

The math stays deterministic and auditable; the LLM only narrates. Raw observations never cross the host boundary — see [Privacy & the egress boundary](docs/concepts/privacy-and-egress.md).

## Documentation

Full docs live in **[docs/](docs/README.md)**. Start here:

- [Overview](docs/overview.md) — the one-page tour.
- [Quick start](docs/quick-start.md) — install in three commands.
- [Connect HealthSave](docs/connect-healthsave.md) — pair the iOS app.
- [Capture sources](docs/capture/index.md) — Apple Health, plugins, importers, planned lanes.
- [Surfaces](docs/surfaces/observatory-web.md) — Observatory web app, findings & Body Briefs, Grafana.
- [API](docs/api/index.md) — frozen v1 ingest contract and the v2 read API.
- [Operations](docs/operations/deployment.md) — deployment, local LLM, reverse proxy, backups, metrics, multi-user, troubleshooting.
- [Development](docs/development/dev-setup.md) — dev setup and pluggable storage backends.

## Roadmap

- Ship the Observatory web app as the default surface; keep Grafana as an optional view.
- Weekly evidence-linked Body Briefs and a first-class finding-card schema.
- A private CLI + local MCP server so your own agents can query your body data.
- Android Health Connect + a generic, HMAC-signed ingest envelope.
- Trend-based alerts and recovery-aware automations via Home Assistant.

Full plan: [docs/roadmap.md](docs/roadmap.md).

## License

The product core is **source-available** under the [Elastic License 2.0](LICENSE) (self-host freely; you may not offer it to third parties as a managed service). The protocol and client layer (`contracts/`, the API client, and the plugin SDK) is **Apache-2.0** so anything can speak the format. See [docs/licensing.md](docs/licensing.md) and [LICENSING.md](LICENSING.md) for the per-path map, and [TRADEMARK.md](TRADEMARK.md) for the name policy.

## Just want the app?

[**HealthSave**](https://apps.apple.com/app/id6759843047) (the HealthSave iOS app) is the Apple Health bridge for your Observatory — and it also runs standalone: on-device Dashboard, Trends, and Export to CSV / JSON / PDF, no account, nothing in the cloud. Self-hosting the Observatory is what adds the longitudinal record you own, the dashboard, the Body Briefs, the routes to your other tools, and the private API.
