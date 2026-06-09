# Troubleshooting

Common issues when running a self-hosted Observatory, and how to diagnose them. Most first-time problems are resource limits or a service that didn't come up — the logs say which.

## The Ollama container won't start

```bash
docker compose logs ollama
```

The most common causes are:

- **Not enough free RAM** — Ollama refuses to load a model that won't fit. Pick a smaller model (see [Local LLM](local-llm.md)) or free up memory.
- **The override file is missing** — re-run `./setup.sh`; it copies the example.
- **Another process is holding port 11434** — stop it, or edit `docker-compose.override.yml` to bind a different port.

## My briefing came back empty (or said "not enough data")

Two things to check:

1. **Has HealthSave actually synced?** Hit `http://your-server-ip:8000/api/apple/status` — if the table counts are all zero, sync from your phone first.
2. **How much history do you have?** The statistical engine needs at least ~24 hours of heart-rate data to compute anything. Newly-installed users typically see a real briefing on day 2.

## I want to change the model after setup

Edit the `OLLAMA_MODEL=` line in your `.env`, then pull the new tag and restart:

```bash
# Edit .env to set OLLAMA_MODEL=<new-tag>
docker compose exec ollama ollama pull <new-tag>
docker compose restart api
```

Any Ollama model tag works — the tier table in [Local LLM](local-llm.md) is a starting point, not a requirement. Browse [ollama.com/library](https://ollama.com/library) for the full list.

## `./setup.sh doctor` says a service isn't running

Run `docker compose logs <service>` (e.g. `docker compose logs api`) to see why. Most first-time failures are Docker not having enough memory allocated — bump it in Docker Desktop's preferences and re-run `./setup.sh`.

## The app can't reach the server

The HealthSave app syncs to the host's LAN IP on port 8000, **not** `localhost`. Run `./setup.sh doctor` to print the exact URL, and confirm the address in the app matches `http://your-server-ip:8000`. If you're going through a [reverse proxy](reverse-proxy.md), use the `https://` hostname with no port. Check that the host firewall allows inbound 8000 (or 443 behind a proxy) on your LAN.

## The Observatory web app or Grafana isn't reachable from another device

Grafana and the database port bind to `127.0.0.1` by default so they aren't exposed on your LAN. To reach Grafana from another device, set `GRAFANA_BIND=0.0.0.0` in `.env` and recreate the stack. For anything beyond your LAN, front it with a [reverse proxy](reverse-proxy.md) rather than binding services to all interfaces.

## See also

- [Local LLM](local-llm.md) — model sizing and changing the model
- [Metrics](metrics.md) — alerting on failing briefings
- [Deployment](deployment.md) — bringing the stack up correctly
