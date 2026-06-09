# Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/) installed and
running, plus a terminal. On Windows, run this inside WSL2 — `setup.sh` is a bash
script. macOS and Linux are fine natively.

## Install in three commands

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./setup.sh
```

That's it. `setup.sh`:

1. Generates secure passwords and writes a `.env` for you.
2. Asks if you want the AI briefing system, then **detects your RAM + GPU and
   recommends the right Ollama model** (you can override).
3. Brings the whole stack up with `docker compose up -d`.

Re-running `./setup.sh` is safe — it preserves passwords and updates only the
AI-related config based on your answers.

## Confirm it's healthy

```bash
./setup.sh doctor
```

The doctor confirms every service is healthy and prints the exact iOS-app URL to
paste into the HealthSave app under Settings → Server Sync.

## Next steps

- [Deployment](operations/deployment.md) — running on a VM, a NAS, or a homelab
  box, and the manual (`setup.sh`-free) path.
- [Local LLM](operations/local-llm.md) — choosing the Ollama model for the optional
  AI briefing by RAM and GPU.
- [Connect HealthSave](connect-healthsave.md) — pair the iOS app and start syncing.
