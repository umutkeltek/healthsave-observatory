# Zero To Ready

This guide takes a clean machine from no checkout to a running HealthSave Observatory stack that the HealthSave iOS app can sync to.

## 1. Choose Platform

| Platform | Use this path |
|---|---|
| macOS | Install Docker Desktop, start it, then use Terminal. |
| Linux | Install Docker Engine or Docker Desktop, then use your shell. |
| WSL2 | Install Docker Desktop on Windows, enable WSL integration, then run HealthSave commands inside WSL2. |
| Native Windows | Use the PowerShell installer as a WSL2 handoff. Native Windows Compose install is not supported yet. |
| Termux | Not supported because Docker Compose is required. |

## 2. Open Onboarding

Recommended when Node.js is available:

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

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/umutkeltek/healthsave-observatory/main/install.ps1 | iex
```

All paths open the same guided control center. Use arrow keys and Enter. Choose Basic setup for the first run unless you already know you need custom passwords, an API key, local AI, or optional layers.

## 3. Basic Setup

Basic setup:

- Creates or preserves `.env`.
- Creates or preserves `config.yaml`.
- Generates database and Grafana passwords when they are missing.
- Starts the default Docker Compose stack.
- Leaves local AI, agents, MQTT, and Home Assistant off until you choose them.

Default services:

| Layer | Service | Purpose | URL |
|---|---|---|---|
| Database | `db` | TimescaleDB canonical health record | `127.0.0.1:5432` |
| Migrations | `migrate` | Schema migration job | n/a |
| API | `api` | FastAPI ingest/read API | `http://localhost:8000` |
| Worker | `worker` | Findings, summaries, and recovery jobs | n/a |
| Observatory web | `web` | Primary product surface | `http://localhost:4173` |
| Grafana | `grafana` | Power-user dashboard | `http://localhost:3000` |

Optional layers:

| Layer | Start from CLI |
|---|---|
| Local AI / Ollama | `healthsave up --ai` |
| Agents | `healthsave up --agents` |
| MQTT broker | `healthsave up --mqtt` |
| Home Assistant bridge | `healthsave up --home-assistant` |

## 4. Verify Local Health

```bash
healthsave doctor
healthsave status
healthsave layers
```

Expected local URLs:

- Observatory web: `http://localhost:4173`
- API readiness: `localhost:8000/ready`
- Grafana: `http://localhost:3000`

`healthsave doctor` also prints the LAN URL to use from the iPhone, for example:

```text
http://<server-lan-ip>:8000
```

Do not use `localhost` from the phone.

## 5. Connect HealthSave iOS

1. Open HealthSave on iPhone.
2. Go to Settings -> Server Sync.
3. Set Server URL to the LAN URL printed by `healthsave doctor`.
4. Set the API key if you configured one during Advanced setup.
5. Tap **Sync New Data**.

The iOS app sends Apple Health data through the frozen v1 ingest contract. The backend normalizes readings into the canonical record used by web, Grafana, findings, integrations, and exports.

## 6. Choose The Right Surface

Use [Observatory web](surfaces/observatory-web.md) for the normal product experience:

```text
http://localhost:4173
```

Use [Grafana](surfaces/grafana.md) for raw SQL-backed chart exploration:

```text
http://localhost:3000
```

The web app explains what changed, what data exists, and where it came from. Grafana serves power users, custom dashboards, and debugging. See [Web vs Grafana](surfaces/web-vs-grafana.md).

## 7. Optional Local AI

Run Advanced setup from the control center, or use:

```bash
healthsave setup advanced
```

Advanced setup detects RAM/GPU, recommends an Ollama model, starts the local AI layer, and pulls the model. Local AI narrates already-computed findings; it does not compute medical facts. See [Local LLM](operations/local-llm.md).

## 8. Optional Home Assistant / MQTT

If you already run an MQTT broker:

```bash
HA_MQTT_ENABLED=true HA_MQTT_BROKER=mqtt.home.arpa healthsave up --home-assistant
```

Put `HA_MQTT_USERNAME` and `HA_MQTT_PASSWORD` in `.env` instead of shell history when the broker requires credentials.

If you want HealthSave to run a bundled broker too:

```bash
HA_MQTT_ENABLED=true healthsave up --mqtt --home-assistant
```

The bridge publishes MQTT discovery and state topics so Home Assistant can create entities without database credentials. See [Home Assistant & MQTT](integrations/home-assistant.md).

## 9. Automation Path

Agents and CI should use scriptable commands instead of the TUI:

```bash
healthsave setup basic --no-input
healthsave doctor --json
healthsave status --json
healthsave layers --json
healthsave logs api
```

Fresh machines without a global install can use `npx --yes healthsave setup basic --no-input`. That is an automation command, not the main human install path.

## 10. Manual Checkout

Use this when npm is unavailable or you want to inspect the checkout first:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave onboard
```

`./healthsave` is the repo-local launcher. The installed command is `healthsave`.

## 11. Stop Or Inspect

```bash
healthsave logs api
healthsave logs web
healthsave down
```

If anything fails, start with:

```bash
healthsave doctor
healthsave logs api
```
