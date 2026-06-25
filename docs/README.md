# HealthSave Observatory Documentation

HealthSave Observatory is a self-hosted private body observatory: bring health data into a canonical record you own, see what changed against your own baseline, get evidence-linked findings, and route/query from your own tools. Raw data stays on your hardware unless you explicitly send it elsewhere.

Apple Health is the most polished shipped capture path, but every source resolves into the same canonical model.

New here? Read [Overview](overview.md), follow [Zero To Ready](zero-to-ready.md), then [Connect HealthSave](connect-healthsave.md).

## Start

- [Overview](overview.md) - one-page tour of what ships today, what is planned, what runs locally, and how health data moves from sources to surfaces.
- [Zero To Ready](zero-to-ready.md) - clean-machine path from `npx healthsave` to running stack, iOS sync, web, Grafana, optional AI, and Home Assistant.
- [Quick Start](quick-start.md) - shorter install path with the core commands.
- [Connect HealthSave](connect-healthsave.md) - pair the HealthSave iOS app to the self-hosted backend and test the frozen v1 Apple Health ingest path.

## Concepts

- [The private body observatory](concepts/private-body-observatory.md) - product thesis: one owned longitudinal health record, local analysis, no diagnostic claims.
- [Source / Device / Stream](concepts/source-device-stream.md) - identity model that keeps integrations, physical devices, and metric streams distinct.
- [Canonical observations](concepts/canonical-observations.md) - append-only raw readings, typed values, provenance, and read-time fusion.
- [Privacy & egress boundary](concepts/privacy-and-egress.md) - default-deny egress, local narration, opt-in redacted cloud paths.

## Capture

- [Capture overview](capture/index.md) - source status: shipped Apple Health/plugins/importers and planned Health Connect/webhook ingest.
- [Apple Health](capture/apple-health.md) - how HealthSave pushes HealthKit metrics into the frozen v1 ingest contract.
- [Direct plugins: Whoop & Amazfit](capture/plugins-whoop-amazfit.md) - how early Whoop/Amazfit poll plugins work and their credential caveats.
- [Importers: Garmin & Samsung](capture/importers-garmin-samsung.md) - sideload Garmin and Samsung/Huawei exports through the same ingest path.
- [Roadmap: Android Health Connect & webhooks](capture/roadmap-android-webhooks.md) - planned universal ingest for HMAC-signed compatible clients.
- [v2 read API](api/v2-read-api.md) - private read/query API for dashboards, scripts, future CLI/MCP clients.

## Surfaces

- [Observatory web app](surfaces/observatory-web.md) - primary insight-first web surface.
- [Web vs Grafana](surfaces/web-vs-grafana.md) - separation between product UX and power-user dashboards.
- [Grafana](surfaces/grafana.md) - bundled SQL-backed power-user dashboard.
- [Findings & Body Briefs](surfaces/findings-and-body-briefs.md) - deterministic findings and local narration.

## Integrations

- [Home Assistant & MQTT](integrations/home-assistant.md) - publish HealthSave signals into Home Assistant through MQTT discovery/state topics.

## Operations

- [Deployment](operations/deployment.md) - run the stack with Docker Compose on a laptop, VM, NAS, or homelab host.
- [CLI distribution](operations/cli-distribution.md) - npm/npx path, repo-local fallback, and Homebrew release shape.
- [Local LLM](operations/local-llm.md) - choose and operate the optional Ollama model that narrates local findings.
- [Reverse proxy & HTTPS](operations/reverse-proxy.md) - expose API safely over HTTPS behind a reverse proxy.
- [Security model](operations/security.md) - API keys, fail-closed auth, network exposure, secret storage, egress limits, backup security.
- [Backup & migrations](operations/backup-and-migrations.md) - back up the TimescaleDB volume and apply migrations safely.
- [Metrics](operations/metrics.md) - scrape Prometheus metrics for ingest throughput, latency, and briefing health.
- [Multi-user / household](operations/multi-user.md) - use `owner_id` to separate multiple residents on one backend.
- [Troubleshooting](operations/troubleshooting.md) - diagnose first-run sync, service, AI, network, and dashboard failures.

## Development

- [Dev setup](development/dev-setup.md) - set up Python 3.12 development and run the same checks as CI.
- [Storage backends](development/storage-backends.md) - implement or register a custom ingest backend while preserving idempotent writes.

## Project

- [Roadmap](roadmap.md) - release sequence: web app, Body Briefs, CLI/MCP, universal ingest, hosted options.
- [Licensing](licensing.md) - open-core map: Apache-2.0 protocol/SDK, ELv2 core, reserved managed layer.
