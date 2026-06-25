# HealthSave Observatory

[![CI](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml)
[![License: Elastic 2.0](https://img.shields.io/badge/License-Elastic--2.0-005571.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515.svg?logo=postgresql&logoColor=white)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Download on the App Store](https://img.shields.io/badge/Download-App%20Store-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/app/id6759843047)

HealthSave Observatory is the self-hosted backend for HealthSave. The iOS app can export and sync Apple Health data; Observatory gives that data a private server, web surface, Grafana dashboards, API, optional local AI briefings, and Home Assistant/MQTT routes.

Raw observations stay on hardware you control unless you enable an egress route.

## Recommended Install

Use the CLI if you already have Node.js:

```bash
npm i -g healthsave
healthsave onboard
```

No global install:

```bash
npx healthsave
```

The command opens the guided control center. Use Basic setup for the first run. Use Advanced setup when you want to set passwords, an API key, local AI/Ollama, or optional layers yourself.

## One-Line Installer

Use this path on servers or clean machines where Node may not be installed.

macOS, Linux, WSL2:

```bash
curl -fsSL https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.ps1 | iex
```

Windows support uses WSL2 today. Install Docker Desktop, enable WSL integration for your Linux distro, then run the PowerShell installer or run the Unix command inside WSL2.

## What You Get

- **Capture without a new silo.** HealthSave iOS syncs Apple Health data into your server. Wearable plugins and file importers follow the same canonical model.
- **One record you own.** Source / Device / Stream identity keeps integrations, physical devices, and metric streams separate without fragmenting your history.
- **Two surfaces.** Observatory web is the product surface for daily use. Grafana stays bundled for raw SQL-backed dashboards and builder workflows.
- **Evidence-linked findings.** The worker computes findings from your stored history. Local AI can narrate those findings, but it does not invent health facts.
- **Private routes.** Scripts, notebooks, agents, Home Assistant, MQTT, and exports can consume selected signals under your policy.

## Default Stack

Basic setup starts TimescaleDB, migrations, the FastAPI API, worker jobs, Observatory web, and Grafana.

```text
HealthSave iOS / Apple Health
        |
        v
FastAPI API -> TimescaleDB -> worker findings
        |
        +-> Observatory web
        +-> Grafana
        +-> Private API / CLI / agents
        +-> Home Assistant / MQTT / export
```

## Connect HealthSave iOS

1. Open [HealthSave](https://apps.apple.com/app/id6759843047) on iPhone.
2. Go to Settings -> Server Sync.
3. Set Server URL to the LAN URL printed by `healthsave doctor`, for example `http://<server-lan-ip>:8000`.
4. Set the API key if you configured one.
5. Tap **Sync New Data**.

Do not use `localhost` from the phone. `localhost` would point at the phone itself.

HealthSave iOS also works without Observatory: on-device dashboard, trends, and CSV/JSON/PDF export do not need an account or a cloud server.

## Automation

Humans should start with `healthsave onboard` or `npx healthsave`. Agents and CI should use named commands:

```bash
healthsave setup basic --no-input
healthsave doctor --json
healthsave status --json
healthsave layers --json
healthsave logs api
```

## Manual Checkout

Use this when you want to inspect the repo before setup:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave onboard
```

## Compatibility

HealthSave Observatory runs on macOS, Linux, and WSL2 with Docker Compose v2. Native Windows install is a WSL2 handoff for now. Termux is not supported because the stack requires Docker Compose.

## Documentation

- [Zero To Ready](docs/zero-to-ready.md) - clean-machine path from install to synced iOS data.
- [Quick Start](docs/quick-start.md) - short setup path and health checks.
- [Deployment](docs/operations/deployment.md) - run on a laptop, VM, NAS, or homelab box.
- [CLI distribution](docs/operations/cli-distribution.md) - npm/npx, installers, repo-local launcher, and Homebrew release shape.
- [Web vs Grafana](docs/surfaces/web-vs-grafana.md) - product surface versus power-user dashboard.
- [Home Assistant & MQTT](docs/integrations/home-assistant.md) - bridge HealthSave signals into Home Assistant.
- [API](docs/api/index.md) - ingest/read API and app connection details.

## License

HealthSave Observatory core is source-available under Elastic License 2.0. Protocol and SDK components may carry separate Apache-2.0 licensing where noted.
