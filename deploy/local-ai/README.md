# Local AI — a private, on-host narrator

The "easy local" path for HealthSave Observatory's LLM narrator (ADR-0003 D8).
A bundled [Ollama](https://ollama.com) sidecar runs the model **on your own
host**, so your weekly Body Brief is written with **zero cloud egress** — no
API key, no opt-in, nothing leaves the box.

## One command

```bash
deploy/local-ai/setup-local-ai.sh
# smaller / faster on a CPU-only host:
MODEL=llama3.2:3b deploy/local-ai/setup-local-ai.sh
```

It starts the sidecar (compose `local-ai` profile), pulls the model, and
verifies it answers. Then open **Observatory → Intelligence → Local**, pick the
model, **Test connection**, and **Save** — or set `LLM_PROVIDER=ollama` in your
`.env` and `docker compose up -d api worker`.

## What you get

- A real narrator at `http://ollama:11434`, reachable only on the internal
  compose network (no host port, no LAN exposure).
- `OLLAMA_NO_CLOUD=1` — Ollama's cloud-model offload is disabled, so a route
  classified **local** can never silently proxy to `ollama.com`. Local means
  local.
- Models live in the `ollama_models` volume; they're pulled on setup, not baked
  into the image.

## Notes

- **GPU:** the base service is CPU-only (works everywhere, including macOS where
  Docker has no GPU passthrough). On an NVIDIA Linux host, add a device
  reservation in a compose override for a big speedup.
- **Already running Ollama?** On the Intelligence → Local screen, click *Detect
  a local model* — the server probes the sidecar and `host.docker.internal` and
  fills in the URL + installed models for you.
- **CPU is slow** for large models. Start with a small one (`llama3.2:3b`) and
  size up if your host can handle it.
