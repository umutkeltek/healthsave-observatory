# HealthSave Observatory — Documentation

This is the documentation for **HealthSave Observatory**, a self-hosted private
body observatory: bring your health data into a canonical record you own, see
what changed against your own baseline with evidence-linked findings, and query
or route it from your own tools — with raw data that never leaves your hardware
unless you choose to send it. Apple Health is the most polished shipped path;
all sources resolve into the same canonical model.

New here? Read the [overview](overview.md), then run the
[quick start](quick-start.md) and [connect the HealthSave app](connect-healthsave.md).

## Start

- [Overview](overview.md) — one-page tour of what ships today, what is planned, what runs locally, and how health data moves from sources to surfaces.
- [Quick start](quick-start.md) — install the self-hosted backend with Docker, run health checks, and get the LAN URL for the HealthSave iOS app.
- [Connect HealthSave](connect-healthsave.md) — pair the HealthSave iOS app with your self-hosted backend and test the frozen v1 Apple Health ingest path.

## Concepts

- [The private body observatory](concepts/private-body-observatory.md) — the product thesis: one owned longitudinal health record, local analysis, and no diagnostic claims.
- [Source / Device / Stream](concepts/source-device-stream.md) — the identity model that keeps integrations, physical devices, and metric streams distinct.
- [Canonical observations](concepts/canonical-observations.md) — the canonical observation model: append-only raw readings, typed values, provenance, and read-time fusion.
- [Privacy & the egress boundary](concepts/privacy-and-egress.md) — the trust boundary: default-deny egress, local narration, and opt-in redacted cloud paths.

## Capture

- [Capture overview](capture/index.md) — capture status by source: shipped Apple Health/plugins/importers and planned Health Connect/webhook ingest.
- [Apple Health](capture/apple-health.md) — how HealthSave pushes HealthKit metrics into the frozen v1 ingest contract.
- [Direct plugins: Whoop & Amazfit](capture/plugins-whoop-amazfit.md) — how the early Whoop and Amazfit poll plugins work, what they emit, and their credential caveats.
- [Importers: Garmin & Samsung](capture/importers-garmin-samsung.md) — use CLI importers to sideload Garmin and Samsung/Huawei exports through the same ingest path.
- [Roadmap: Android Health Connect & webhooks](capture/roadmap-android-webhooks.md) — planned universal ingest: HMAC-signed canonical batches for Health Connect, webhooks, and custom sources.

## Surfaces

- [Observatory web app](surfaces/observatory-web.md) — pre-release primary web surface for baseline, provenance, evidence, and privacy views over the v2 API.
- [Findings & Body Briefs](surfaces/findings-and-body-briefs.md) — how deterministic findings become daily briefings today and productized weekly Body Briefs next.
- [Grafana](surfaces/grafana.md) — bundled optional Grafana dashboards for raw, SQL-backed metric exploration.

## Integrations

- [Home Assistant](integrations/home-assistant.md) — publish selected health metrics to Home Assistant through MQTT discovery, with direct SQL as a legacy/example path.

## API

- [API overview](api/index.md) — API map: frozen v1 ingest, evolving v2 read/query, auth, and stability rules.
- [v1 Apple contract](api/v1-apple-contract.md) — byte-stable Apple Health ingest contract for the iOS app and compatible clients.
- [v2 read API](api/v2-read-api.md) — pre-stable private read/query API for dashboards, scripts, and future CLI/MCP clients.

## Operations

- [Deployment](operations/deployment.md) — run the stack with Docker Compose on a laptop, VM, NAS, or homelab host.
- [Local LLM](operations/local-llm.md) — choose and operate the optional Ollama model that narrates local findings.
- [Reverse proxy & HTTPS](operations/reverse-proxy.md) — expose the API safely over HTTPS behind a reverse proxy instead of publishing plain HTTP.
- [Security model](operations/security.md) — API keys, fail-closed auth, network exposure, secret storage, egress limits, and backup security for a self-hosted health-data stack.
- [Backup & migrations](operations/backup-and-migrations.md) — back up the TimescaleDB volume and apply additive migrations safely.
- [Metrics](operations/metrics.md) — scrape Prometheus metrics for ingest throughput, latency, and briefing health.
- [Multi-user / household](operations/multi-user.md) — use `owner_id` to separate multiple residents on one backend.
- [Troubleshooting](operations/troubleshooting.md) — diagnose first-run sync, service, AI, network, and dashboard failures.

## Development

- [Dev setup](development/dev-setup.md) — set up Python 3.12 development and run the same format/lint/test/build checks as CI.
- [Storage backends](development/storage-backends.md) — implement or register a custom ingest backend while preserving idempotent writes.

## Project

- [Roadmap](roadmap.md) — release sequence from core coherence to web app, Body Briefs, CLI/MCP, universal ingest, and hosted options.
- [Licensing](licensing.md) — plain-English open-core map: Apache-2.0 protocol/SDK, ELv2 core, and reserved managed layer.
