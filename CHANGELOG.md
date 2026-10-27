# Changelog

Every tagged release of HealthSave Observatory, newest first. Self-hosters
install tags, not `main`; see [RELEASING.md](RELEASING.md) for how a release is
cut and [UPGRADING.md](UPGRADING.md) for upgrade detail.

Versions follow [semantic versioning](https://semver.org): tag `vX.Y.Z`.
Plugins carry their own versions.

## [Unreleased]

### Security

- The Observatory web dashboard asks for a password when `WEB_PASSWORD` is set.
  Setup generates one for new installs, and `healthsave pair` shows it. Without
  a session, pages redirect to `/login` and every data route (including the
  `/api/*` pass-through to the API) returns `401`. An older `.env` without
  `WEB_PASSWORD` behaves as before, and `healthsave doctor` warns when such a
  dashboard listens on anything but loopback, or when the dashboard has a
  password but the API has no key. Session cookies are also keyed with a
  generated `WEB_SESSION_SECRET`; server actions check the session themselves;
  ten wrong passwords in a minute pause sign-in; sign-in and sign-out refuse
  cross-site posts.
- `healthsave setup basic` now generates an API key. A fresh install no longer
  accepts unauthenticated reads and writes from everyone on your network.
  Existing installs keep their `.env` untouched.
- New `healthsave pair` shows the server URL, the API key and, when `qrencode`
  is installed, a QR code for the HealthSave app. `healthsave pair --new-key`
  rotates the key and restarts the API and web.
- `healthsave doctor` warns when no API key is set.
- Advanced setup suggests a generated key instead of open access.

- `SECURITY.md` says how to report a vulnerability privately.
- The reverse-proxy example no longer carries the maintainer's hostnames and
  LAN address: `server_name _`, and `generate-self-signed.sh` takes
  `CERT_HOSTNAMES` / `CERT_IPS`.

### Added

- `healthsave backup` writes the database (`pg_dump`), `.env` and
  `config.yaml` to one owner-only `.tar` file. `healthsave restore FILE`
  saves the current database first, then restores with TimescaleDB's
  pre/post-restore steps, checks the migration count, and restarts the
  services it stopped. It refuses a backup from a different TimescaleDB version.

### Changed

- The bundled Mosquitto broker requires a login when `MOSQUITTO_USERNAME` and
  `MOSQUITTO_PASSWORD` are set. Setup generates both for new installs, and
  `healthsave up --home-assistant` prints them for Home Assistant's MQTT
  integration. The bridge falls back to this login when `HA_MQTT_USERNAME` and
  `HA_MQTT_PASSWORD` are empty. An older `.env` keeps the broker anonymous,
  with a warning in its logs.
- Setup turns on the four analysis jobs that need no AI model (anomalies,
  trends, correlations, recovery) when it writes a new `config.yaml`, so
  Findings fill in without any AI setup. Advanced setup now keeps them on when
  you skip Ollama. Existing `config.yaml` files and `config.yaml.example` are
  unchanged.

- The AI narrator no longer downloads LiteLLM's model price list from GitHub
  each time LiteLLM loads (it uses the bundled copy), and LiteLLM telemetry is
  off. Bundled Grafana no longer sends usage reports or checks for updates.
  Neither request carried health data, but neither went through the egress
  gate.

### Fixed

- The installers check out the newest `vX.Y.Z` release instead of `main`.
  `npx healthsave` defaulted to a `v0.1.5` tag that never existed, so a fresh
  `npx` install failed. Set `HEALTHSAVE_OBSERVATORY_REF` (or `--ref`) to pick a
  tag, branch or commit. The npm bootstrapper is now 0.2.0.

## [1.1.0] - 2026-10-04

The first tagged release since 1.0.0. It contains everything built since May,
including the ingest fixes that came from HealthSave iOS users' reports.

### Upgrade

```bash
git fetch --tags
git checkout v1.1.0
docker compose up -d --build
```

The `migrate` service applies migrations `001` to `027` before the API starts.
Every migration is additive: no table is renamed or dropped, and existing rows
are kept. Read the R1 and R2 notes in [UPGRADING.md](UPGRADING.md) before
upgrading an install that started on 1.0.0.

### Fixed

- Concurrent uploads that revise the same sample, under a new uuid or with a
  changed device or source attribution, no longer reject their batch.
- Database deadlocks and serialization failures are answered as retryable
  server errors instead of `422`, so the app retries the batch instead of
  giving up on it.
- A sample that HealthKit revises under a new uuid at the same timestamp no
  longer rejects its batch.
- A workouts or sleep batch from two devices reaches the v1 tables again.
- `GET /api/apple/coverage` answers per wire metric, in the shape the app
  decodes.
- Current Apple unit strings are accepted; mixed-source device attribution is
  kept; revised HealthKit daily totals replace the old value safely; duplicate
  conflict keys inside one batch are merged before the upsert.
- A deterministic bad payload is answered `422`, never `500`. Clients retry
  `5xx` indefinitely, so a deterministic `500` blocked a metric for good.
- Request bodies, batches and exports have size limits.

### Added

- `POST /api/v2/apple/batch` (HealthSave iOS 1.7.2 and later): each sample
  carries its HealthKit uuid, interval bounds and unit; deletions travel with
  the batch; iOS 1.8.0 and later declare whether a value is one sample or a
  day total.
- A canonical observation store with a source, device and stream registry,
  read through `/api/v2/*`: metrics, series, receipts, changes, insights,
  readiness, privacy, experiments, moments and settings.
- The HealthSave Observatory web app (`apps/web`).
- Sync accounting: delivery receipts, sync run summaries
  (`/api/v2/sync/runs/*`) and `GET /api/apple/coverage` for the app's recovery
  lane.
- Medication dose events and heartbeat series (the beat-to-beat data behind
  an HRV reading, sent by iOS 1.8.5 and later when switched on).
- Statistical findings and a weekly Body Brief. Narration is optional; cloud
  providers are opt-in and receive derived findings only, never raw rows.
- A Home Assistant MQTT bridge with its own namespace and a liveness watchdog.
- Authorization helpers for Whoop, Polar, Google Health and Amazfit, and
  importers for Garmin and Samsung exports (`scripts/`).
- Release discipline: this changelog, [RELEASING.md](RELEASING.md) and a
  release gate that refuses a tag whose version disagrees with the code.

### Docs

- `uuid` is required on every anchored sample, medication dose events
  included ([#45](https://github.com/umutkeltek/healthsave-observatory/issues/45)).

### Compatibility

- The routes the App Store app depends on are unchanged: `POST /api/apple/batch`,
  `GET /api/apple/status` and `GET /api/health`.
- Every HealthSave iOS release can still sync over v1. iOS 1.7.2 and later use
  the v2 batch route when the server offers it. Use the current App Store
  release; its sync repairs work together with the server fixes above.

## [1.0.0] - 2026-05-03

First tagged release, published as "Health Data Hub": a self-hosted Apple
Health server with TimescaleDB, Grafana and Ollama briefings, paired with the
HealthSave iOS app.

The `v1.0.0` tag later went missing from GitHub. It was re-created on
2026-10-04 at `ba7ddfe`, the commit the release was published from (its author
time matches the release's creation time to the second).
