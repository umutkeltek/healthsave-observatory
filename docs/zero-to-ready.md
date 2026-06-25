# Zero To Ready

This guide takes a clean machine from no checkout to a running HealthSave
Observatory stack that the HealthSave iOS app can sync to.

## 1. Choose Platform Path

- **macOS:** install Docker Desktop, start it, and use Terminal.
- **Linux:** install Docker Engine or Docker Desktop, then use your shell.
- **Windows:** install Docker Desktop, enable WSL2 integration, and run commands
  inside a WSL2 Linux shell. Native PowerShell is not the supported install path
  for the Docker Compose stack.

The recommended install uses `npx`, so the machine needs Node.js 18+ with npm
and npx. If you do not want Node on the server, use the manual checkout fallback
in section 9.

## 2. Install And Start

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

`npx healthsave` clones or reuses the HealthSave Observatory checkout, installs
the local `healthsave` wrapper when possible, then delegates to the same CLI
inside the checkout.

Use `healthsave tui` after install for the human control center. It supports
arrow keys and Enter for setup, stack up/down, optional layer toggles,
doctor/status, logs, verification, and CLI installation. Agents and automation
should use the named subcommands shown in this guide.

Choose one setup mode:

- **Basic setup:** best first run. Generates local passwords, writes `.env`,
  creates `config.yaml`, skips AI questions, and starts the default stack.
- **Advanced setup:** guided prompts for passwords, API key, local AI/Ollama,
  and model choice.

Automation should use:

```bash
npx healthsave setup basic ~/healthsave-observatory --no-input
```

## 3. What Starts In Basic Setup

Basic setup starts the default application stack:

| Layer | Service | Purpose | URL |
|---|---|---|---|
| Database | `db` | TimescaleDB canonical health record | `127.0.0.1:5432` |
| Migrations | `migrate` | Schema migration job | n/a |
| API | `api` | FastAPI ingest/read API | `http://localhost:8000` |
| Worker | `worker` | Findings, summaries, recovery jobs | n/a |
| Observatory web | `web` | Primary web surface | `http://localhost:4173` |
| Grafana | `grafana` | Power-user dashboard | `http://localhost:3000` |

Optional layers are not started by Basic setup:

| Layer | Service | Start With |
|---|---|---|
| Local AI / Ollama | `ollama` | `healthsave setup advanced` or `healthsave up --ai` |
| Agents | `agents` | `healthsave up --agents` |
| MQTT broker | `mqtt` | `healthsave up --mqtt` |
| Home Assistant bridge | `homeassistant-mqtt` | `healthsave up --home-assistant` |

## 4. Verify

```bash
healthsave doctor
healthsave status
healthsave layers
```

`doctor` checks platform tools, config files, running services, and URLs.
`status` shows Docker state by product layer. `layers` explains what every layer
is for.

Expected first-run URLs:

- Observatory web: `http://localhost:4173`
- API readiness: `localhost:8000/ready`
- Grafana: `http://localhost:3000`

The CLI also prints a LAN URL for iPhone, for example:

```text
http://<your-lan-ip>:8000
```

Use the LAN URL in the iOS app. Do not use `localhost` from the phone.

## 5. Connect HealthSave iOS

1. Open HealthSave on iPhone.
2. Go to Settings -> Server Sync.
3. Set Server URL to the LAN URL printed by `healthsave doctor`.
4. If you configured an API key in Advanced setup, set it in the app too.
5. Tap **Sync New Data**.

The app sends Apple Health data to the frozen v1 ingest contract. The backend
normalizes it into the canonical record used by web, Grafana, findings, and
integrations.

## 6. Choose Daily Surface

Use [Observatory web](surfaces/observatory-web.md) for the normal product
experience:

```text
http://localhost:4173
```

Use [Grafana](surfaces/grafana.md) when you want raw SQL-backed dashboards and
chart exploration:

```text
http://localhost:3000
```

See [Web vs Grafana](surfaces/web-vs-grafana.md) for the separation.

## 7. Optional: Local AI

Run:

```bash
healthsave setup advanced
```

Advanced setup detects RAM/GPU, recommends an Ollama model, starts the local AI
layer, and pulls the model. Local AI narrates already-computed findings; it does
not compute health facts. See [Local LLM](operations/local-llm.md).

## 8. Optional: Home Assistant / MQTT

If you already run an MQTT broker:

```bash
HA_MQTT_ENABLED=true \
HA_MQTT_BROKER=<your-mqtt-host> \
healthsave up --home-assistant
```

If you want HealthSave to run a bundled broker too:

```bash
HA_MQTT_ENABLED=true healthsave up --mqtt --home-assistant
```

See [Home Assistant](integrations/home-assistant.md) for topics, discovery
entities, and safety notes.

## 9. Manual Checkout Fallback

Use this path when you do not want Node/npm/npx on the server:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave setup basic
./healthsave doctor
./healthsave tui
./healthsave install-cli
```

`./healthsave` is the repo-local launcher. The installed command is `healthsave`.

## 10. Stop Or Inspect

```bash
healthsave logs api
healthsave logs web
healthsave down
```

If anything fails, start with:

```bash
healthsave doctor
healthsave logs <layer>
```
