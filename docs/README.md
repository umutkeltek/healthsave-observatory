# HealthSave Observatory Documentation

HealthSave Observatory is a self-hosted private body observatory. It brings health data into a canonical record you own, compares changes against your own baseline, computes evidence-linked findings, and lets your tools query or route selected signals.

Raw data stays on your hardware unless you enable an egress route. Apple Health through the HealthSave iOS app is the most polished shipped capture path today. Other sources resolve into the same canonical model.

New here? Start with [Zero To Ready](zero-to-ready.md), then [Connect HealthSave](connect-healthsave.md).

## Start

- [Overview](overview.md) - what ships today and how health data moves through sources, storage, surfaces, and routes.
- [Zero To Ready](zero-to-ready.md) - clean-machine path from install to iOS sync, web, Grafana, optional AI, and Home Assistant.
- [Quick Start](quick-start.md) - shorter install path and core commands.
- [Connect HealthSave](connect-healthsave.md) - pair the iOS app with the self-hosted backend.

## Concepts

- [Private body observatory](concepts/private-body-observatory.md) - product thesis: one owned longitudinal health record, local analysis, no diagnostic claims.
- [Source / Device / Stream](concepts/source-device-stream.md) - identity model for integrations, physical devices, and metric streams.
- [Canonical observations](concepts/canonical-observations.md) - append-only raw readings, typed values, provenance, and read-time fusion.
- [Privacy & egress boundary](concepts/privacy-and-egress.md) - default-deny egress, local narration, and opt-in redacted cloud paths.

## Capture

- [Capture overview](capture/index.md) - source status across Apple Health, wearable plugins, importers, planned Health Connect, and webhook ingest.
- [Apple Health](capture/apple-health.md) - how HealthSave iOS pushes HealthKit metrics into the frozen v1 ingest contract.
- [Plugins: Whoop & Amazfit](capture/plugins-whoop-amazfit.md) - early direct plugin architecture and OAuth token storage.
- [Importers: Garmin & Samsung](capture/importers-garmin-samsung.md) - file/importer path into the same canonical model.
- [Android & webhook roadmap](capture/roadmap-android-webhooks.md) - planned Health Connect and generic signed ingest.

## API

- [API overview](api/index.md) - stable v1 ingest versus evolving v2 read/query APIs.
- [v1 Apple contract](api/v1-apple-contract.md) - frozen app compatibility contract.
- [v2 read API](api/v2-read-api.md) - private read plane for scripts, dashboards, and future CLI/MCP clients.

## Surfaces

- [Observatory web](surfaces/observatory-web.md) - primary product UX.
- [Grafana](surfaces/grafana.md) - bundled SQL-backed power-user dashboard.
- [Web vs Grafana](surfaces/web-vs-grafana.md) - product UX versus raw dashboard boundary.
- [Findings & Body Briefs](surfaces/findings-and-body-briefs.md) - deterministic findings and optional local narration.

## Integrations

- [Home Assistant & MQTT](integrations/home-assistant.md) - publish HealthSave signals through MQTT discovery/state topics.

## Operations

- [Deployment](operations/deployment.md) - run the stack on a laptop, VM, NAS, Proxmox host, or homelab box.
- [CLI distribution](operations/cli-distribution.md) - installer, npm/npx path, repo-local fallback, and Homebrew release shape.
- [Local LLM](operations/local-llm.md) - choose and operate the optional Ollama narration model.
- [Reverse proxy & HTTPS](operations/reverse-proxy.md) - expose API surfaces safely behind HTTPS.
- [Security model](operations/security.md) - API keys, fail-closed auth, network exposure, secret storage, egress limits, and backup security.
- [Backup & migrations](operations/backup-and-migrations.md) - back up TimescaleDB and apply migrations safely.
- [Metrics](operations/metrics.md) - scrape Prometheus metrics for ingest throughput, latency, and briefing health.
- [Multi-user / household](operations/multi-user.md) - use `owner_id` to separate multiple residents on one backend.
- [Troubleshooting](operations/troubleshooting.md) - diagnose first-run sync, service, AI, network, and dashboard failures.

## Development

- [Dev setup](development/dev-setup.md) - set up Python 3.12 development and run the same checks as CI.
- [Storage backends](development/storage-backends.md) - implement custom ingest backends while preserving idempotent writes.

## Project

- [Roadmap](roadmap.md) - release sequence: web app, Body Briefs, CLI/MCP, universal ingest, hosted options.
- [Licensing](licensing.md) - open-core map: Apache-2.0 protocol/SDK, ELv2 core, reserved managed layer.
