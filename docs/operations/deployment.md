# Deployment

HealthSave Observatory is plain Docker Compose, so anything that runs Docker runs it — a laptop, a NUC, a Mac mini, a Synology NAS, or a Proxmox VM. This page covers deploying it on a homelab box and reaching it from your phone.

## Docker Compose

The whole stack comes up with one command. The guided path is `./setup.sh` (it generates passwords and writes `.env` for you); the manual path is below.

### Manual quick-start (without `setup.sh`)

```bash
cp .env.example .env
# Edit .env with your passwords

docker compose up -d
```

This starts:

- **TimescaleDB** on port 5432
- **FastAPI** (the Observatory API) on port 8000
- **Grafana** on port 3000 (default login: `admin` / your `GRAFANA_PASSWORD`)

`./setup.sh` is the easier path — it generates the passwords for you. On the manual path, set `DB_PASSWORD` and `GRAFANA_PASSWORD` in `.env` first; Compose requires them, so the project never ships guessable defaults.

The database port and Grafana are bound to `127.0.0.1` by default, so they are available for local tooling without being exposed on your LAN. To reach Grafana from another device, set `GRAFANA_BIND=0.0.0.0` in `.env`.

To opt into the local-LLM briefing manually, copy `docker-compose.override.yml.example` to `docker-compose.override.yml`, copy `config.yaml.example` to `config.yaml`, set `analysis.daily_briefing.enabled` and `analysis.anomaly_detection.enabled` to `true`, and set `OLLAMA_MODEL` in `.env`. See [Local LLM](local-llm.md) for model sizing.

## Proxmox, a NAS, or a homelab box

### VM vs LXC

- **Easiest: a small VM.** Create a Debian 12 / Ubuntu 22.04+ VM, give it roughly 2 vCPU and 4 GB RAM (comfortable for ingest + TimescaleDB + Grafana), install Docker, then run `./setup.sh`. Add RAM — or pass through an NVIDIA GPU — only if you want the local AI briefing (see [Local LLM](local-llm.md) for the RAM-to-model mapping).
- **Container route: a Docker-capable LXC.** Works too, but Docker-in-LXC wants a privileged container (or `nesting=1` + `keyctl=1`) and is fiddlier than a VM. If you're unsure, use the VM.

### Storage

TimescaleDB is the only stateful piece — point its Docker volume at a disk you back up. History grows slowly (roughly megabytes per month for one person), so it stays light. See [Backups & migrations](backup-and-migrations.md) for what to back up and how migrations apply on upgrade.

## Reaching it from your phone

The HealthSave iOS app syncs to the host's LAN IP on port 8000, **not** `localhost`. After the stack is up, run `./setup.sh doctor` — it prints the exact URL to paste into the app.

In the app, go to **Settings → Server Sync** and set the Server URL to your host's address, for example:

```
http://your-server-ip:8000
```

Set your API key as well if you configured one in `.env`, then tap **Sync New Data**.

> Don't expose plain HTTP to the internet. For remote access, put the API behind a reverse proxy that terminates HTTPS — see [Reverse proxy](reverse-proxy.md).

## See also

- [Reverse proxy](reverse-proxy.md) — HTTPS and production posture
- [Backups & migrations](backup-and-migrations.md) — back up the database volume, apply schema upgrades
- [Local LLM](local-llm.md) — sizing the optional Ollama briefing model
