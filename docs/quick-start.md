# Quick Start

HealthSave Observatory runs as a Docker Compose stack. Install Docker first, then let the CLI guide setup.

## Platform

- macOS: use Docker Desktop.
- Linux: use Docker Engine or Docker Desktop.
- WSL2: enable Docker Desktop WSL integration for your Linux distro.
- Native Windows: use WSL2 today; the stack does not install directly from PowerShell.
- Termux: unsupported because Docker Compose is required.

## Recommended Path

```bash
npm i -g healthsave
healthsave onboard
```

No global install:

```bash
npx healthsave
```

Server or clean-machine installer. Docker Compose v2 still needs to be installed and running:

```bash
curl -fsSL https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.sh | bash
```

Windows PowerShell handoff to WSL2:

```powershell
irm https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.ps1 | iex
```

`healthsave onboard` opens the arrow-key control center for Basic setup, Advanced setup, stack control, optional layers, doctor/status, logs, verification, and CLI installation.

## Setup Modes

- Basic setup: generates local passwords, writes `.env`, creates `config.yaml`, skips AI questions, and starts TimescaleDB, API, worker, Observatory web, and Grafana.
- Advanced setup: asks for passwords, API key, local AI/Ollama, and model choice.

Re-running setup preserves existing `.env` and `config.yaml` values unless you edit them.

## Confirm Health

```bash
healthsave doctor
healthsave status
healthsave layers
```

`doctor` checks platform tools, config files, service health, and URLs. `status` shows Docker state by product layer. `layers` explains API, database, worker, web, Grafana, local AI, agents, MQTT, and Home Assistant.

## Automation

Agents and CI should use named commands:

```bash
healthsave setup basic --no-input
healthsave doctor --json
healthsave status --json
healthsave logs api
```

## Manual Checkout

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave onboard
```

After checkout setup works, `./healthsave install-cli` installs a `healthsave` wrapper in `~/.local/bin`.

## Next

- [Zero To Ready](zero-to-ready.md) - full clean-machine guide through iOS sync, web, Grafana, optional AI, and Home Assistant.
- [Deployment](operations/deployment.md) - run on a VM, NAS, Proxmox VM, or homelab box.
- [Local LLM](operations/local-llm.md) - choose an optional AI briefing model by RAM and GPU.
- [Connect HealthSave](connect-healthsave.md) - pair the iOS app and start syncing.
- [Home Assistant & MQTT](integrations/home-assistant.md) - publish HealthSave signals into Home Assistant.
