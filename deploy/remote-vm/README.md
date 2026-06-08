# Remote VM Deployment

This deploys Health Data Hub as a reference server on a remote Docker host over SSH.
Use it when you want a small, repeatable VM install without handing Docker Compose
files around manually.

Defaults:

- Runtime host: set with `REMOTE_HOST`
- Remote code: `/srv/stacks/health-data-hub`
- Remote secrets/env: `/srv/localappdata/health-data-hub/.env`
- API: `http://<REMOTE_HOST>:18080`
- Grafana: `http://<REMOTE_HOST>:3300`
- Postgres/TimescaleDB: bound to `127.0.0.1:15432` on the VM only
- Home Assistant MQTT profile: **disabled by default**

Deploy from a clean repository:

```bash
REMOTE_HOST=your-vm.example ./deploy/remote-vm/deploy.sh
```

Use an existing external Postgres/TimescaleDB host instead of the bundled
Compose database:

```bash
REMOTE_HOST=your-vm.example \
HEALTH_DATA_HUB_DATABASE_MODE=external \
HEALTH_DATA_HUB_DB_HOST=postgres.example.internal \
HEALTH_DATA_HUB_DB_PORT=5432 \
HEALTH_DATA_HUB_DB_NAME=healthsave \
HEALTH_DATA_HUB_DB_USER=healthsave \
./deploy/remote-vm/deploy.sh
```

External mode still reads `DB_PASSWORD` from the remote env file, runs the
migration service, starts API + worker + Grafana, and leaves the bundled `db`
service stopped.

Verify:

```bash
curl -fsS http://your-vm.example:18080/health
curl -fsS http://your-vm.example:18080/api/health
curl -fsS http://your-vm.example:18080/ready
curl -fsS http://your-vm.example:3300/api/health
ssh your-vm.example 'cat /srv/localappdata/health-data-hub/current-release.env'
```

Important boundaries:

- Do not point this script at an existing production app directory. It replaces the
  contents of `REMOTE_DIR` after archiving the chosen git commit.
- If `HEALTH_DATA_HUB_DATABASE_MODE=external`, confirm the external database is
  backed up before deployment. The script applies forward migrations to that
  database.
- Do not enable `homeassistant-mqtt` against an existing Home Assistant broker until
  you review topic prefixes; otherwise it may publish overlapping retained
  discovery/state topics.
- Treat this as a reference deployment lane. For public internet exposure, put a
  reverse proxy with TLS **and per-IP rate limiting** in front of the API and
  Grafana. A ready-to-use nginx config + compose override lives in
  [`../reverse-proxy/`](../reverse-proxy/) (SECURITY-004) — layer its override
  **last** so it removes the direct API port publish and becomes the only ingress.
