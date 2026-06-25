# Deployment

HealthSave Observatory is a Docker Compose stack. It can run on a laptop, NUC, Mac mini, Synology NAS, Proxmox VM, or small Linux server as long as Docker Compose v2 works.

## Supported Platforms

- macOS: Docker Desktop.
- Linux: Docker Engine or Docker Desktop.
- WSL2: Docker Desktop WSL integration enabled.
- Native Windows: use WSL2 today.
- Termux: not supported because Docker Compose is required.

## Guided Setup

Recommended:

```bash
curl -fsSL https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.sh | bash
```

Package-manager path:

```bash
npm i -g healthsave && healthsave onboard
```

No global install:

```bash
npx healthsave
```

`healthsave onboard` opens the control center for setup, stack up/down, optional layer toggles, doctor/status, logs, verification, and local CLI installation.

## Default Stack

Basic setup starts:

- TimescaleDB on port 5432.
- FastAPI Observatory API on port 8000.
- Worker jobs for findings, summaries, and recovery.
- Observatory web on port 4173.
- Grafana on port 3000 with login `admin` and your `GRAFANA_PASSWORD`.

Advanced setup adds guided choices for database password, Grafana password, API key, and local AI/Ollama.

## Manual Checkout

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git && cd healthsave-observatory && ./healthsave onboard
```

`./setup.sh` remains a compatibility wrapper. Public docs and agent instructions should use `healthsave onboard` for humans and named `healthsave ...` commands for automation.

## Manual Compose

If you do not want guided setup:

```bash
cp .env.example .env && cp config.yaml.example config.yaml && docker compose up -d
```

Edit `.env` first and set at least `DB_PASSWORD` and `GRAFANA_PASSWORD`. HealthSave does not ship guessable production default secrets.

Database, Grafana, and Observatory web bind to loopback by default where applicable. To reach web or Grafana from another device on your LAN, set bind addresses deliberately:

```bash
GRAFANA_BIND=0.0.0.0
WEB_BIND=0.0.0.0
```

Do not expose plain HTTP directly to the internet. For remote access, put the API, Observatory web, and Grafana behind HTTPS with deliberate auth; see [Reverse proxy](reverse-proxy.md).

## Optional Local AI

Use Advanced setup from the control center, or run:

```bash
healthsave setup advanced
```

Manual path:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Then edit `.env`, `config.yaml`, `OLLAMA_MODEL`, and analysis settings. See [Local LLM](local-llm.md) for model sizing by RAM/GPU.

## Proxmox, NAS, Homelab

For a first install, use a small Debian 12 or Ubuntu 22.04+ VM. A reasonable baseline is 2 vCPU and 4 GB RAM for ingest, TimescaleDB, API, web, and Grafana. Add RAM/GPU only if you want local AI briefing.

Docker-capable LXC can work, but Docker-in-LXC often needs privileged container settings. A VM is simpler for most users.

TimescaleDB is the stateful piece. Put Docker volumes on reliable storage and follow [Backups & migrations](backup-and-migrations.md).

## Connect iOS App

Open HealthSave on iPhone, then Settings -> Server Sync. Use the LAN URL printed by `healthsave doctor`, for example:

```text
http://<server-lan-ip>:8000
```

Do not use `localhost` from the phone. Set the API key if you configured one, then tap **Sync New Data**.

## See Also

- [Zero To Ready](../zero-to-ready.md) - clean-machine install guide.
- [Reverse proxy](reverse-proxy.md) - HTTPS production posture.
- [Backups & migrations](backup-and-migrations.md) - database backups and upgrades.
- [Local LLM](local-llm.md) - optional Ollama briefing model.
