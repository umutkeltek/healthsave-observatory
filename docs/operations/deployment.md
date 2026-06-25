# Deployment

HealthSave Observatory is plain Docker Compose. Anything that can run Docker can run it: laptop, NUC, Mac mini, Synology NAS, Proxmox VM, or a small Linux server.

## Supported Platforms

- macOS: Docker Desktop is the easiest path.
- Linux: Docker Engine or Docker Desktop works.
- Windows: use WSL2 with Docker Desktop WSL integration enabled, then run `healthsave` inside the WSL2 shell.

## Guided Docker Compose Setup

Use the published CLI path for normal installs:

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

Basic setup starts the default stack:

- **TimescaleDB** on port 5432
- **FastAPI** Observatory API on port 8000
- **Worker** for findings, summaries, and recovery jobs
- **Observatory web** on port 4173
- **Grafana** on port 3000, login `admin` / your `GRAFANA_PASSWORD`

Advanced setup adds guided choices for API key and local AI/Ollama:

```bash
npx healthsave setup advanced ~/healthsave-observatory
```

`./setup.sh` remains a compatibility wrapper. `./healthsave` remains the
repo-local checkout launcher. New docs and agent instructions should use
`npx healthsave ...` for first install and `healthsave ...` after the wrapper is
installed.

`healthsave tui` is the interactive control center for post-install operation:
setup, stack up/down, optional layer toggles, doctor/status, logs, and
verification.

Manual checkout fallback:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave setup basic
./healthsave doctor
```

## Manual Quick Start

If you do not want the guided setup:

```bash
cp .env.example .env
# Edit .env with DB_PASSWORD and GRAFANA_PASSWORD.
cp config.yaml.example config.yaml
docker compose up -d
```

On the manual path, set `DB_PASSWORD` and `GRAFANA_PASSWORD` in `.env` first. Compose requires them, so the project never ships guessable defaults.

Database, Grafana, and Observatory web bind loopback by default where applicable. To reach Grafana or web from another device on your LAN, set these deliberately in `.env`:

```bash
GRAFANA_BIND=0.0.0.0
WEB_BIND=0.0.0.0
```

Do not expose plain HTTP to the internet. For remote access, put the API and surfaces behind a reverse proxy that terminates HTTPS; see [Reverse proxy](reverse-proxy.md).

## Optional Local AI

For local-LLM briefing, use:

```bash
healthsave setup advanced ~/healthsave-observatory
```

Or manually copy the override and set the model:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
# Edit .env and config.yaml for OLLAMA_MODEL and analysis enablement.
docker compose up -d
```

See [Local LLM](local-llm.md) for model sizing by RAM and GPU.

## Proxmox, NAS, Homelab Box

Use a small VM if you are unsure: Debian 12 or Ubuntu 22.04+, roughly 2 vCPU and 4 GB RAM for ingest, TimescaleDB, API, web, and Grafana. Add RAM and GPU passthrough only if you want local AI briefing.

Docker-capable LXC can work, but Docker-in-LXC is more fiddly and often needs privileged container settings. For a first install, a VM is simpler.

TimescaleDB is the stateful piece. Put Docker volumes on reliable storage and follow [Backups & migrations](backup-and-migrations.md).

## Connect The iOS App

Open HealthSave on iPhone, then Settings -> Server Sync.

Use:

```text
http://your-server-ip:8000
```

Do not use `localhost` from the phone. Set the API key as well if you configured one in `.env`, then tap **Sync New Data**.

## See Also

- [Reverse proxy](reverse-proxy.md) - HTTPS production posture
- [Backups & migrations](backup-and-migrations.md) - back up the database volume and apply schema upgrades
- [Local LLM](local-llm.md) - sizing the optional Ollama briefing model
