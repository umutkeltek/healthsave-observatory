# Security model

How HealthSave Observatory protects a self-hosted health-data stack: the threat
model it assumes, API-key auth and fail-closed behavior, what is exposed on the
network, where secrets live, the cloud-egress boundary, backup security, and the
limits you should know about today.

This page is the single place to reason about trust. For the data-flow side of
the boundary — what crosses to a cloud model and what never does — see
[Privacy & the egress boundary](../concepts/privacy-and-egress.md).

## Threat model

The Observatory is designed as a **LAN-first, self-hosted** application: it runs
on hardware you control (a laptop, a NUC, a Mac mini, a NAS, a homelab VM) and is
**not internet-exposed by default**. The expected deployment is a private network
where the people on it are trusted; the iOS app reaches the backend over the LAN.

It is *not* designed to be published to the open internet as plain HTTP. If you
need remote access, that is an explicit step you take deliberately — terminate
HTTPS at a [reverse proxy](reverse-proxy.md) and never expose port 8000 directly.

## Auth

The PHI surface (`/api/apple/*` and the v2 read API) is gated by an API key:

- **`X-API-Key`** — `healthsave setup` generates a long random `API_KEY` in
  `.env`. `healthsave pair` shows it (and a QR code for the HealthSave app);
  `healthsave pair --new-key` rotates it. Requests without the key are rejected.
- **Keyless means refused, unless you opt out.** If `API_KEY` is empty, the PHI
  surface is *refused* (`503`) unless `ALLOW_NO_AUTH=true` is set. The bundled
  `docker-compose.yml` sets that opt-out by default so a bare
  `docker compose up` works as a local demo, and the API logs a loud warning on
  every start. `healthsave doctor` flags it too. Leave authentication on for any
  deployment that holds real data.

A handful of endpoints are intentionally unauthenticated because they expose no
health data: `/health`, `/api/health`, and `/ready` (liveness/readiness), and
`/metrics` (see below).

## Network exposure

What listens, and what to do about it:

- **API (`:8000`)** — the only surface that should be reachable by the app.
  Keep it on the LAN; for remote access, front it with HTTPS via a
  [reverse proxy](reverse-proxy.md).
- **Grafana (`:3000`)** — bundled dashboards. Set a strong `GRAFANA_PASSWORD` and
  do not publish it to the internet.
- **Database (`:5432`)** — TimescaleDB. Keep it bound to localhost or a private
  Docker network. **Never** publish 5432 to the internet.
- **`/metrics`** — the Prometheus endpoint is **unauthenticated by design** so a
  scraper on a private network does not need a key. If you expose it beyond your
  LAN, protect it behind the same reverse proxy. See [Metrics](metrics.md).

## Secret storage

- **`.env`** holds `API_KEY`, `GRAFANA_PASSWORD`, `DB_PASSWORD`, any cloud
  `LLM_API_KEY`, and `HDH_TOKEN_ENC_KEY`. Keep it out of version control
  (it is gitignored) and readable only by the user that runs the stack.
- **Plugin tokens are encrypted at rest.** Third-party OAuth/refresh tokens for
  the Whoop and Amazfit poll plugins are encrypted with a Fernet key
  (`HDH_TOKEN_ENC_KEY`) before they are stored. Generate the key once, set it in
  `.env`, and treat it like any other secret — losing it means re-authorizing
  those plugins.

## Egress

The egress boundary is the core privacy guarantee:

- **Raw observations never leave the host.** No raw health rows are sent to any
  cloud service, by default or otherwise.
- **Cloud AI is opt-in and derived-only.** If you deliberately point the narrator
  at a cloud model, a default-deny egress gate still guarantees only derived
  findings and the assembled, on-device-redacted prompt cross the boundary —
  never raw rows.

The full data-flow detail, the redaction step, and the local-vs-cloud paths are
documented in [Privacy & the egress boundary](../concepts/privacy-and-egress.md).

### Outbound calls the stack makes by itself

None that you did not turn on. Bundled Grafana has usage reporting, update
checks and the news feed switched off, and the AI narrator loads LiteLLM with
its bundled model price list (`LITELLM_LOCAL_MODEL_COST_MAP`) and telemetry
off, so it does not fetch from GitHub on import. The connectors you enable
(Whoop, Amazfit and others) call their vendors, and a cloud AI model you
configure receives the redacted prompt. Ollama runs with `OLLAMA_NO_CLOUD=1`.

## Backup security

Your backups contain the same health data the live database does, so protect them
the same way:

- Back up the TimescaleDB data volume (volume snapshots or `pg_dump` — see
  [Backups & migrations](backup-and-migrations.md)).
- **Encrypt backups at rest**, especially if they leave the host (offsite copies,
  cloud object storage, removable media). An unencrypted dump on a shared drive
  defeats the local-first posture.
- Restrict who can read the backup location, and rotate any credentials used to
  write to remote backup targets.

## Known limits

Be honest about what is and isn't there today:

- **Single shared API key.** There is one `API_KEY` for the PHI surface today —
  every client that holds it has the same access. **Scoped read tokens are
  planned** so you can hand a narrow, revocable token to a script, dashboard, or
  agent without sharing the full key.
- **No built-in TLS.** The API speaks plain HTTP; HTTPS is your reverse proxy's
  job. Don't skip it for anything beyond the LAN.
- **Trust within the LAN is assumed.** The default posture trusts the local
  network; harden it (segmentation, the reverse proxy, Grafana auth) if your LAN
  is shared with untrusted devices.
- **The Observatory web dashboard has no login yet.** It binds to `127.0.0.1`
  by default. If you set `WEB_BIND=0.0.0.0`, anyone who can reach port 4173 sees
  your data. Put it behind the reverse proxy with authentication until a login
  ships.
- **The egress gate covers the AI narrator only.** The Home Assistant MQTT
  bridge, exports and Grafana send data where you point them without passing
  through it.
- **Health data is not encrypted by the stack.** Use disk encryption on the
  host (FileVault, LUKS, or your NAS's encrypted volumes).

## See also

- [Privacy & the egress boundary](../concepts/privacy-and-egress.md) — what crosses to the cloud and what never does
- [Reverse proxy](reverse-proxy.md) — terminating HTTPS for any access beyond your LAN
- [Backups & migrations](backup-and-migrations.md) — protecting the data volume
- [Metrics](metrics.md) — the unauthenticated scrape endpoint
