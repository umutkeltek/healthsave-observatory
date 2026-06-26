# Troubleshooting

Most first-time problems are Docker not running, Docker lacking memory, a service failing to start, or the phone using the wrong URL.

Start with:

```bash
./healthsave doctor
./healthsave status
```

Then inspect the failing layer:

```bash
./healthsave logs api
./healthsave logs web
./healthsave logs grafana
```

## Docker Is Not Running

`doctor` reports Docker CLI, daemon, and Compose plugin separately.

- macOS: start Docker Desktop.
- Linux: start Docker Engine or Docker Desktop.
- Windows: run inside WSL2 with Docker Desktop WSL integration enabled.

## A Service Is Not Running

Use layer aliases:

```bash
./healthsave logs database
./healthsave logs api
./healthsave logs worker
./healthsave logs web
./healthsave logs grafana
```

Most first-time failures are Docker memory limits or missing config. If config is missing:

```bash
./healthsave setup basic
```

## App Cannot Reach Server

The HealthSave iOS app syncs to the host's LAN IP on port `8000`, not `localhost`.

Run:

```bash
./healthsave doctor
```

Use the printed iOS app URL, for example:

```text
http://<your-lan-ip>:8000
```

If you use a reverse proxy, use the `https://` hostname with no port. Check that the host firewall allows inbound `8000` on LAN, or `443` through the proxy.

## Observatory Web Or Grafana Is Not Reachable From Another Device

Observatory web and Grafana expose private health data, so they bind loopback by default.

For deliberate LAN access, set:

```bash
WEB_BIND=0.0.0.0
GRAFANA_BIND=0.0.0.0
```

Then restart:

```bash
./healthsave up
```

For anything beyond LAN, use a reverse proxy with HTTPS instead of binding services directly to the internet.

## Ollama Container Will Not Start

Check:

```bash
./healthsave logs ai
```

Common causes:

- not enough free RAM for the selected model
- another process using port `11434`
- local AI was partially configured manually

Use a smaller model or rerun:

```bash
./healthsave setup advanced
```

## Briefing Is Empty Or Says Not Enough Data

Check two things:

1. Has the phone synced? Open `http://your-server-ip:8000/api/apple/status`.
2. Is there enough history? The statistical engine needs roughly a day of data before useful briefings appear.

New installs usually get better results on day two.

## Change Ollama Model

Edit `OLLAMA_MODEL=` in `.env`, then pull the model and restart the worker:

```bash
docker compose exec ollama ollama pull qwen3:8b
docker compose restart worker
```

See [Local LLM](local-llm.md) for sizing.

## See Also

- [Zero To Ready](../zero-to-ready.md)
- [Deployment](deployment.md)
- [Local LLM](local-llm.md)
- [Metrics](metrics.md)
