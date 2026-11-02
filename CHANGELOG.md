# Changelog

Every tagged release of HealthSave Observatory, newest first. Self-hosters
install tags, not `main`; see [RELEASING.md](RELEASING.md) for how a release is
cut and [UPGRADING.md](UPGRADING.md) for upgrade detail.

Versions follow [semantic versioning](https://semver.org): tag `vX.Y.Z`.
Plugins carry their own versions.

## [Unreleased]

## [1.2.0] - 2026-11-03

A new install is locked down from the first start: it gets an API key, a
dashboard password and a QR code to pair the app. Releases now ship as
pre-built images, and `healthsave update`, `backup` and `restore` handle
upgrades and backups. Observatory Care, an optional licence, adds encrypted
off-site backups, restore drills and update rollback. Everything that was free
stays free.

### Upgrade

```bash
git fetch --tags
git checkout v1.2.0
docker compose up -d
```

- From this release on, `docker compose up -d` pulls pre-built images for
  `linux/amd64` and `linux/arm64` instead of building them on your machine.
  To keep building from source, add the build override:
  `docker compose -f docker-compose.yml -f docker-compose.build.override.yml up -d --build`.
- Two additive migrations run on the first `docker compose up -d`: `028_lab_results`
  (blood test results) and `029_api_keys` (participant keys). They add tables and
  change nothing you already have; the `migrate` service applies them before the
  API starts, as always.
- Your `.env` is not changed. An install without an API key, dashboard
  password or broker login keeps working as before, and `healthsave doctor`
  says what is open. `healthsave pair --new-key` adds a key; then pair the
  phone again.
- For later releases, `healthsave update` does all of this for you, and takes
  a backup first.

### Security

- `healthsave setup basic` now generates an API key. A fresh install no longer
  accepts unauthenticated reads and writes from everyone on your network.
  Existing installs keep their `.env` untouched.
- New `healthsave pair` shows the server URL, the API key and, when `qrencode`
  is installed, a QR code for the HealthSave app. `healthsave pair --new-key`
  rotates the key and restarts the API and web.
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
- `healthsave doctor` warns when no API key is set.
- Advanced setup suggests a generated key instead of open access.
- `SECURITY.md` says how to report a vulnerability privately.
- The reverse-proxy example no longer carries the maintainer's hostnames and
  LAN address: `server_name _`, and `generate-self-signed.sh` takes
  `CERT_HOSTNAMES` / `CERT_IPS`.

### Added

- Pre-built images for `linux/amd64` and `linux/arm64`, signed with cosign:
  `ghcr.io/umutkeltek/healthsave-observatory` (API, migrations, worker, agents
  and the Home Assistant bridge) and `ghcr.io/umutkeltek/healthsave-observatory-web`.
  `docker-compose.yml` pulls the images of the release you checked out;
  `docker-compose.build.override.yml` builds them from source instead.
- Lab results. `healthsave labs import FILE.csv` loads blood test results with
  LOINC ids; `GET /api/v2/labs` and `GET /api/v2/labs/{loinc}` return each marker
  against the lab's own printed range and your own history. Results from two labs
  stay separate rows and are never averaged. A Labs page shows the trend per
  marker and one cross-match card (ferritin against resting heart rate) with its
  coverage and limits. (migration `028_lab_results`)
- Participants. One Observatory can hold several people. `healthsave participants
  add NAME` prints a pairing code for the free app; the data lands under that
  person's own key. The `.env` API key stays the admin key and sees everyone;
  `GET /api/v2/owners` lists people, nine `/api/v2/*` reads take `?owner=`, and the
  web dashboard gets a participant switcher. `healthsave participants revoke`
  refuses a key everywhere. The phone routes are unchanged. (migration
  `029_api_keys`)
- Home Assistant pack under `integrations/home-assistant/pack/`: three blueprints
  (wind-down from sleep length, a recovery-aware morning in plain words, a
  low-data warning) and a plain-cards Body dashboard, built on the bridge's own
  `sensor.healthsave_observatory_*` entities.
- Observatory Care, an optional licence for people who want their install
  looked after ([docs](docs/operations/observatory-care.md)):
  `healthsave backup --encrypt`, `--offsite REMOTE` (through rclone, to storage
  you own) and `--schedule daily|weekly`; `healthsave restore --drill FILE`,
  which restores a backup into a throwaway database and compares every table's
  row count; and `healthsave update --rollback`. `healthsave license` installs
  and shows the licence file, which is checked on your machine against a
  built-in public key and never phones home. Encrypted backups still restore
  without a licence.
- Remote access without opening ports: an optional `tailscale` Compose profile
  serves the web app and the API on your tailnet over HTTPS, with no router
  port opened and Funnel off. See
  [Remote access](docs/operations/remote-access.md).
- Settings -> Web sign-in sets, changes or turns off the dashboard password
  (changes need the current password; this browser stays signed in, others are
  signed out). It is stored as a salted scrypt hash in the new `web_data`
  volume and takes over from `WEB_PASSWORD`. `healthsave web-password reset`
  removes it when the password is lost.
- `healthsave update [--to TAG]` moves a git install to the newest release:
  backup first, then checkout of the tag, then a restart of exactly the
  services that were running, on the new release's images. It refuses local
  edits to tracked files and prints the way back if the new release does not
  start.
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
- The web app runs on Node.js 22. Node.js 20 no longer gets security fixes.
- Today shows compact readings, links each reading and finding to its
  evidence, and has larger touch targets on phones.

### Fixed

- A fresh install no longer starts with every analysis job off. Compose passes
  an empty `ANALYSIS_*_ENABLED` value when `.env` does not set one, and an
  empty value counted as "off", overriding `config.yaml`. Empty now means "not
  set". The same applies to `LLM_REDACT_CLOUD_PROMPTS`, so an empty value
  keeps cloud-prompt redaction on.
- The installers install the newest published release instead of `main`.
  `npx healthsave` defaulted to a `v0.1.5` tag that never existed, so a fresh
  `npx` install failed. "Newest published" means the GitHub Release, which
  exists only once that release's images are published; without it, the
  newest `vX.Y.Z` tag. Set `HEALTHSAVE_OBSERVATORY_REF` (or `--ref`) to pick a
  tag, branch or commit. The npm bootstrapper is now 0.2.0.
- Activity summaries keep every field when a batch arrives, stand hours
  included.
- Replaying an old batch no longer makes sync readiness report a metric as
  behind when newer data is already stored.
- Testing the AI connection from Settings accepts the same local model hosts
  the server already trusts.

### Compatibility

- The routes the App Store app depends on are unchanged: `POST /api/apple/batch`,
  `GET /api/apple/status` and `GET /api/health`. The OpenAPI lock changed only
  in its version number.
- The remote VM deploy (`deploy/remote-vm/deploy.sh`) still builds from the
  deployed commit, with the same ports and image names as before.

### Known limits
- The Home Assistant / MQTT bridge and the bundled Grafana dashboards still read
  across every person on an Observatory that holds participants; leave the
  bridge off on such an install until it is scoped. Findings and the weekly
  Body Brief are produced for the primary person only.

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
