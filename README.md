# HealthSave Observatory

[![CI](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/umutkeltek/healthsave-observatory/actions/workflows/ci.yml)
[![License: Elastic 2.0](https://img.shields.io/badge/License-Elastic--2.0-005571.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515.svg?logo=postgresql&logoColor=white)](https://www.timescale.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Download on the App Store](https://img.shields.io/badge/Download-App%20Store-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/app/id6759843047)

HealthSave Observatory is a self-hosted place for health data you own. It brings
Apple Health data, early wearable plugins, and file imports into one canonical
record, then gives you a private API, an Observatory web app, Grafana dashboards,
and optional local AI narration.

Raw observations stay on your hardware unless you explicitly route them
elsewhere.

## Quick Start

You need Docker installed and running.

- macOS and Linux are supported directly.
- Windows is supported through WSL2 with Docker Desktop WSL integration enabled.
  Run the commands inside the WSL2 shell.

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

`npx healthsave` creates or finds the stack checkout, installs the local
`healthsave` wrapper when possible, then runs the checkout's setup CLI.

`healthsave tui` opens the arrow-key control center for setup, stack up/down,
optional layer toggles, doctor/status, logs, verification, and CLI installation.
Use named subcommands for automation and agents.

Manual checkout fallback:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave setup basic
./healthsave doctor
./healthsave tui
```

Basic setup starts TimescaleDB, migrations, the API, the worker, Observatory web,
and Grafana. Advanced setup adds guided choices for API key and optional local
AI/Ollama.

Full guide: [Zero To Ready](docs/zero-to-ready.md) | [Quick Start](docs/quick-start.md) | [Deployment](docs/operations/deployment.md) | [Local LLM](docs/operations/local-llm.md)

## What You Get

- **Capture without a new silo.** Apple Health syncs through the HealthSave iOS
  app. Early Whoop/Amazfit/Polar plugins and Garmin/Samsung importers are
  included. Android Health Connect and generic HMAC-signed ingest are planned.
- **One canonical record.** Readings resolve into the same Source / Device /
  Stream model, so new devices do not break dashboards, automations, or
  provenance.
- **Two surfaces.** Observatory web is the primary product surface. Grafana is
  bundled for raw SQL-backed exploration.
- **Deterministic findings, optional narration.** Statistics compute anomalies,
  trends, summaries, and correlations. Local AI only turns already-computed
  findings into readable briefings.
- **Private API and automation routes.** Query your health history from scripts,
  notebooks, agents, Home Assistant, MQTT, and exports.

## Connect HealthSave iOS

1. Open [HealthSave](https://apps.apple.com/app/id6759843047) on iPhone.
2. Go to Settings -> Server Sync.
3. Set Server URL to `http://your-server-ip:8000`. Do not use `localhost` from
   the phone.
4. Optional: set your API key.
5. Tap **Sync New Data**.

The iOS app sends Apple Health data to the frozen v1 ingest contract:
`POST /api/apple/batch`.

## Layers

```text
Capture sources
  HealthSave iOS / Apple Health
  Wearable plugins and importers
  Planned Health Connect and generic ingest

Core stack
  FastAPI API -> TimescaleDB -> worker findings

Surfaces and routes
  Observatory web
  Grafana
  Private API / CLI / agents
  Home Assistant / MQTT / export
```

## Documentation

- [Overview](docs/overview.md)
- [Zero To Ready](docs/zero-to-ready.md)
- [Quick Start](docs/quick-start.md)
- [Connect HealthSave](docs/connect-healthsave.md)
- [Capture sources](docs/capture/index.md)
- [Observatory web](docs/surfaces/observatory-web.md)
- [Grafana](docs/surfaces/grafana.md)
- [Web vs Grafana](docs/surfaces/web-vs-grafana.md)
- [Home Assistant & MQTT](docs/integrations/home-assistant.md)
- [API](docs/api/index.md)
- [Deployment](docs/operations/deployment.md)
- [CLI distribution](docs/operations/cli-distribution.md)
- [Development](docs/development/dev-setup.md)

## Release Notes For Installers

- npm package name: `healthsave`
- npx install path: `npx healthsave setup basic ~/healthsave-observatory`
- repo-local fallback: `./healthsave setup basic`
- Homebrew formula template: `packaging/homebrew/healthsave.rb.template`

## License

HealthSave Observatory core is source-available under the Elastic License 2.0.
Protocol and SDK components may carry separate Apache-2.0 licensing where noted.

The HealthSave iOS app also works standalone: on-device dashboard, trends, and
CSV/JSON/PDF export with no account and no cloud requirement.
