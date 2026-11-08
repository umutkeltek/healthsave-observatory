# Changelog

Every tagged release of HealthSave Observatory, newest first. Self-hosters
install tags, not `main`; see [RELEASING.md](RELEASING.md) for how a release is
cut and [UPGRADING.md](UPGRADING.md) for upgrade detail.

Versions follow [semantic versioning](https://semver.org): tag `vX.Y.Z`.
Plugins carry their own versions.

## [Unreleased]

### Upgrade

- Migrations 030, 031 and 032 are additive and run on boot.
- `HDH_KEYRING` now reaches the `api` and `worker` containers. The code read
  it before, but `docker-compose.yml` never passed it through, so a value in
  `.env` had no effect. Once it does, a non-empty ring decides which key seals
  and opens the saved AI provider keys.
  - **Before you upgrade**, check whether `.env` has a non-empty
    `HDH_KEYRING`. If it is empty or absent, nothing changes. If it is set,
    make sure the key from `HDH_TOKEN_ENC_KEY` is in the ring as a trailing
    `v0:` entry, or the provider keys saved so far will not open.
  - **After you upgrade**, run one narrator connection test (Test connection
    on the Intelligence settings page) to confirm the saved key still opens.

## [1.4.0] - 2026-11-07

Give your AI a body: your own Claude can read your record. `healthsave mcp`
prints one line that connects Claude Code or Claude Desktop to this server,
read-only.

### Upgrade

```bash
healthsave update --to v1.4.0
```

- No migration and no `.env` change on upgrade. `healthsave mcp` adds
  `MCP_READ_KEY` to `.env` the first time you run it.
- The API image now also carries the MCP server
  (`/opt/healthsave-mcp/bin/healthsave-mcp`, in its own environment; the
  server's own packages are unchanged).

### Added

- MCP read server (`packages/mcp`, [Give your AI a body](docs/mcp.md)). Eight
  read-only tools: overview, today against your usual, sleep, activity, one
  metric over time, findings, blood test results and Year in Health. Ask "how
  did I sleep this year?" and it answers from your own record: nights, hours
  asleep, bedtimes, stages, the nights with no data, month by month. Every
  answer carries its units, the endpoints it read and plain limitation codes.
  Two sources are never averaged.
- `healthsave mcp` prints the setup line for Claude Code, the config block for
  Claude Desktop and a Docker line, with this server's address and a read key
  filled in. `healthsave mcp --check` starts the server the way an AI client
  does and calls one tool. `healthsave mcp key --rotate` replaces the key.
- A read key for the primary person. Until now a read key always belonged to a
  participant. The new key reads your readings plus findings, correlations, lab
  results and your time setting, so your AI client never needs the admin key.
  A participant can never be bound to the primary person's record, even with
  the same name as that key.

### Privacy and safety

- The MCP server sends only `GET` requests, to the address you give it and
  nowhere else; it does not follow redirects or use proxy settings. It hands
  your AI per-day, per-night and per-month summaries, not raw readings; lab
  results are listed one by one (at most 20 per marker).
- No read key may call any route that writes. A test now fails the build if
  one ever can.
- What your AI reads goes to that AI's provider, like the rest of your
  conversation. Your record stays on your hardware.

### Not yet

- ChatGPT. It reaches MCP servers from OpenAI's cloud, so it would need your
  Observatory open to the internet.
- A read covers at most 5,000 readings per request; the tools say from which
  day an answer is complete when a long period is cut.


## [1.3.0] - 2026-11-07

Year in Health: one calendar year of your record on one page, with every gap
shown and each device kept separate, plus a share card that carries no
personal numbers unless you add them.

### Upgrade

```bash
healthsave update --to v1.3.0
```

- No migration and no `.env` change. Existing installs keep every setting.
- The new page reads the data you already have; nothing is recomputed or
  rewritten.

### Added

- Year in Health. `/year` in the dashboard shows one calendar year of your
  record: a month-by-month strip of small calendars, one strip per kind of data
  (heart, sleep, activity, body, ...) with every day without data drawn and
  listed, the devices that sent data and when each one started or stopped, and
  a few numbers for each device on its own (two devices are never averaged into
  one number). Low coverage is marked, and a block says what the view cannot
  tell you. `GET /api/v2/year/{year}` returns the same facts for scripts and
  takes `?owner=` like the other person-scoped reads. Days follow your
  analytical time setting (time zone and day start).
- A share card for the year: a 1080 x 1350 SVG drawn on your server (the PNG
  download is made from it in your browser). By default it shows only the shape of the year (which days have data,
  where the gaps are) and the year itself: no counts, no dates, no device
  names. Tick "Show my numbers" or "Show device names" on the page to add them.
  Nothing leaves your server unless you post the file yourself.

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
- The Home Assistant / MQTT bridge publishes one person only. It reads the
  default owner (the person behind the `.env` API key) unless
  `HEALTHSAVE_BRIDGE_OWNER` names another participant's id; a second person's
  rows never reach a published payload.
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
- The bundled Grafana dashboards still read across every person on an
  Observatory that holds participants; filter them per panel or keep Grafana
  off such an install. Findings and the weekly Body Brief are produced for the
  primary person only.

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
