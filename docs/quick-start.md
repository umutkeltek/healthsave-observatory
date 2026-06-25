# Quick Start

You need Docker installed and running.

- macOS: Docker Desktop is the easiest path.
- Linux: Docker Engine or Docker Desktop works.
- Windows: use WSL2 with Docker Desktop WSL integration enabled, then run the
  commands inside the WSL2 shell. Native PowerShell is not the supported install
  path for the Docker Compose stack.

## Install

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

`npx healthsave` creates or finds the HealthSave Observatory checkout, installs
the local `healthsave` command when possible, and delegates setup to that
checkout.

Basic setup generates passwords, writes `.env`, keeps local defaults, skips AI
questions, and starts TimescaleDB, migrations, the API, the worker, Observatory
web, and Grafana.

Use `healthsave tui` after install for the arrow-key control center: setup,
stack control, optional layer toggles, doctor/status, logs, verification, and
local CLI installation.

Use named subcommands for automation and agents.

Advanced setup lets you choose passwords, an API key, local AI/Ollama, and the
model:

```bash
npx healthsave setup advanced ~/healthsave-observatory
```

Re-running setup is safe. Existing `.env` and `config.yaml` values are
preserved.

## Manual Checkout Fallback

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave setup basic
./healthsave doctor
./healthsave tui
```

`./healthsave` is the repo-local launcher for development or manual installs.
After checkout setup works, `./healthsave install-cli` installs the global
`healthsave` wrapper.

## Confirm It Is Healthy

```bash
healthsave doctor
healthsave status
healthsave layers
```

`doctor` confirms platform tools, config files, default services, and URLs.
`status` shows Docker state by product layer. `layers` explains the API,
database, worker, web, Grafana, local AI, agents, MQTT, and Home Assistant
layers.

## Next Steps

- [Zero To Ready](zero-to-ready.md) - full clean-machine guide through iOS sync,
  web, Grafana, local AI, and Home Assistant.
- [Deployment](operations/deployment.md) - running on a VM, NAS, or homelab box.
- [Local LLM](operations/local-llm.md) - choosing an optional AI briefing model
  by RAM and GPU.
- [Connect HealthSave](connect-healthsave.md) - pair the iOS app and start
  syncing.
