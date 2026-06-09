# HealthSave Observatory — Documentation

This is the documentation for **HealthSave Observatory**, a self-hosted private
body observatory: capture your health data from any device, build a canonical
record you own, see what changed against your own baseline with evidence-linked
findings, and query or route it from your own tools — with raw data that never
leaves your hardware unless you choose to send it.

New here? Read the [overview](overview.md), then run the
[quick start](quick-start.md) and [connect the HealthSave app](connect-healthsave.md).

## Start

- [Overview](overview.md) — the one-page tour: what it is, the two ingest lanes, what's local vs self-hosted.
- [Quick start](quick-start.md) — install the backend in three commands.
- [Connect HealthSave](connect-healthsave.md) — pair the HealthSave iOS app and start syncing.

## Concepts

- [The private body observatory](concepts/private-body-observatory.md) — the idea, and why it's not just another dashboard.
- [Source / Device / Stream](concepts/source-device-stream.md) — the stable identity model that keeps dashboards and automations from breaking.
- [Canonical observations](concepts/canonical-observations.md) — how every source normalizes into one record you own.
- [Privacy & the egress boundary](concepts/privacy-and-egress.md) — default-deny egress, on-device redaction, opt-in cloud.

## Capture

- [Capture overview](capture/index.md) — the source-agnostic ingest model, shipped vs planned.
- [Apple Health](capture/apple-health.md) — the iOS bridge and HealthKit metric coverage.
- [Direct plugins: Whoop & Amazfit](capture/plugins-whoop-amazfit.md) — poll-based wearable connectors.
- [Importers: Garmin & Samsung](capture/importers-garmin-samsung.md) — file-based CLI importers.
- [Roadmap: Android Health Connect & webhooks](capture/roadmap-android-webhooks.md) — the planned generic ingest lane.

## Surfaces

- [Observatory web app](surfaces/observatory-web.md) — the primary, insight-first surface.
- [Findings & Body Briefs](surfaces/findings-and-body-briefs.md) — the two-brain analysis and the weekly Body Brief.
- [Grafana](surfaces/grafana.md) — the optional, bundled-today power-user dashboards.

## Integrations

- [Home Assistant](integrations/home-assistant.md) — the MQTT bridge and direct-SQL package.

## API

- [API overview](api/index.md) — the two surfaces: frozen v1 ingest and the evolving v2 read API.
- [v1 Apple contract](api/v1-apple-contract.md) — the frozen ingest contract the iOS app depends on.
- [v2 read API](api/v2-read-api.md) — the typed read surface for your own scripts and tools.

## Operations

- [Deployment](operations/deployment.md) — running on Docker, a VM, a NAS, or a homelab box.
- [Local LLM](operations/local-llm.md) — Ollama model selection by RAM and GPU.
- [Reverse proxy & HTTPS](operations/reverse-proxy.md) — putting the stack behind Caddy/Traefik.
- [Backup & migrations](operations/backup-and-migrations.md) — keeping the TimescaleDB volume safe and up to date.
- [Metrics](operations/metrics.md) — the Prometheus `/metrics` endpoint.
- [Multi-user / household](operations/multi-user.md) — splitting one stack across residents.
- [Troubleshooting](operations/troubleshooting.md) — the common first-run failures.

## Development

- [Dev setup](development/dev-setup.md) — the local verification commands CI runs.
- [Storage backends](development/storage-backends.md) — the pluggable `IngestStorage` protocol.

## Project

- [Roadmap](roadmap.md) — where HealthSave Observatory is going.
- [Licensing](licensing.md) — source-available core, Apache-2.0 protocol/SDK.
