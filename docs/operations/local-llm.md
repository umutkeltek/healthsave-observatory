# Local LLM

Daily briefing narrates deterministic findings with a local language model running through [Ollama](https://ollama.com). The statistical engine computes findings; the model only turns them into prose. Nothing leaves your network unless you opt into cloud egress.

Enable it through Advanced setup:

```bash
healthsave setup advanced
```

## Hardware Recommendations

Different models need different amounts of RAM. `healthsave setup advanced` reads system RAM/GPU and suggests a model. You can still choose any Ollama tag.

| System RAM | No GPU / Apple Silicon | NVIDIA GPU detected |
|---|---|---|
| < 6 GB | too small - skip AI | too small - skip AI |
| 6-10 GB | `llama3.2:1b` (~1.3 GB) | `gemma3:4b` (~3 GB) |
| 10-18 GB | `gemma3:4b` (~3 GB) | `qwen3:8b` (~5 GB) |
| 18-36 GB | `qwen3:8b` (~5 GB) | `qwen3:14b` (~9 GB) |
| 36-96 GB | `qwen3:14b` (~9 GB) | `gemma3:27b` (~17 GB) |
| > 96 GB | `llama3.3:70b` (~40 GB) | `llama4:scout` (MoE, ~40 GB) or `llama3.3:70b` |

Apple Silicon uses unified memory, so system RAM is the relevant limit. Linux boxes with NVIDIA GPUs usually move up one tier because CUDA handles most model work. AMD GPU support depends on Ollama/ROCm coverage, so the installer treats it conservatively.

If the machine has less than 6 GB RAM, skip AI. Ingest, API, web, worker, and Grafana still run; only narrative briefing is disabled.

## Ollama over LAN

"Local Ollama" does not mean "on the same machine". An Ollama instance on
another host in your own network — a GPU box, a NAS, a dedicated server — is
still local: nothing leaves your network, and it is a first-class supported
setup.

1. **On the Ollama machine**, let it listen on the LAN:

   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```

   (Or set `OLLAMA_HOST=0.0.0.0` persistently for the `ollama` service.)

2. **In HealthSave's `config.yaml`**, point the LLM at the LAN host and declare
   it inside the trust boundary:

   ```yaml
   llm:
     provider: "ollama"
     model: "llama3.1:8b"
     base_url: "http://192.168.1.50:11434"   # LAN host or mDNS name, e.g. http://nas.local:11434
     trusted_local_hosts: ["192.168.1.50"]   # or ["nas.local"]
   ```

   Plain `http://` is correct here. HealthSave only requires HTTPS for *cloud*
   endpoints; trusted local and LAN hosts always run over plain HTTP, exactly
   like the bundled sidecar.

3. Restart the worker:

   ```bash
   docker compose restart worker
   ```

How it works: every LLM route is classified against the egress trust boundary
(`llm.trusted_local_hosts` widens "local" beyond loopback and the bundled
sidecar). A LAN host listed there is treated as local — no cloud opt-in, no
redaction, no HTTPS requirement. Without the entry the same URL is refused
fail-closed (as a potential cloud route), and the error message now tells you
to add it.

## Changing Model

You can change the model later. Edit `OLLAMA_MODEL=` in `.env`, pull the new tag, then restart the worker:

```bash
docker compose exec ollama ollama pull qwen3:8b &&
  docker compose restart worker
```

The table is a starting point. Any Ollama model tag can work; browse [ollama.com/library](https://ollama.com/library) for the full list.

## See Also

- [Troubleshooting](troubleshooting.md) - Ollama will not start or briefing is empty.
- [Deployment](deployment.md) - enabling briefing in the stack.
