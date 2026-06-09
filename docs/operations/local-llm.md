# Local LLM

The daily briefing narrates findings with a local language model running through [Ollama](https://ollama.com) — a tiny daemon that runs LLMs on your own machine. The statistical engine computes the findings; the model only turns them into prose. Nothing leaves your network unless you opt into cloud egress. This page covers sizing the model and changing it later.

## Hardware recommendations

Different models need different amounts of RAM. `setup.sh` reads your system RAM + GPU and suggests one — but you can pick any Ollama tag.

| System RAM | No GPU / Apple Silicon | NVIDIA GPU detected |
|---|---|---|
| < 6 GB | *too small — skip AI* | *too small — skip AI* |
| 6–10 GB | `llama3.2:1b` (~1.3 GB) | `gemma3:4b` (~3 GB) |
| 10–18 GB | `gemma3:4b` (~3 GB) | `qwen3:8b` (~5 GB) |
| 18–36 GB | `qwen3:8b` (~5 GB) | `qwen3:14b` (~9 GB) |
| 36–96 GB | `qwen3:14b` (~9 GB) | `gemma3:27b` (~17 GB) |
| > 96 GB | `llama3.3:70b` (~40 GB) | `llama4:scout` (MoE, ~40 GB) or `llama3.3:70b` |

A quick translation:

- **Apple Silicon Macs** (M1/M2/M3/M4) use unified memory, so system RAM ≈ what the model can use. A 16 GB MacBook Air handles `gemma3:4b` comfortably; a 64 GB Studio runs `qwen3:14b` with headroom.
- **Linux box with an NVIDIA GPU** — Ollama uses CUDA. The recommendation bumps a tier because the GPU absorbs most of the work.
- **AMD GPU on Linux** — Ollama can use ROCm but coverage varies; treated as CPU-only in the recommendation logic.
- **Intel Macs and Windows-without-WSL** — fall back to CPU-only conservative defaults; still works, just slower.

These picks default to the **2026 instruction-tuned generations** (Llama 3.3, Qwen 3, Gemma 3, Llama 4 Scout) because the briefing is a narrative-prose task — generalist chat models beat reasoning specialists like DeepSeek-R1 here. Older `llama3.1:8b` / `qwen2.5:14b` still work fine if that's what you have pulled; the table is a recommendation, not a requirement. Llama 4 Scout uses Mixture-of-Experts, so only ~17 B parameters are active per token, which is why it fits the 70 B-class slot despite its 109 B total parameter count.

If you're on something smaller than 6 GB RAM (a Pi 4, an old NAS), `setup.sh` will recommend skipping AI entirely. The ingest pipeline still runs — you just won't get the morning narrative.

## Changing the model

You can change the model later at any time. Edit the `OLLAMA_MODEL=` line in your `.env`, then pull the new tag and restart:

```bash
# Edit .env to set OLLAMA_MODEL=<new-tag>
docker compose exec ollama ollama pull <new-tag>
docker compose restart api
```

The tier table above is a starting point — any Ollama model tag works. Browse [ollama.com/library](https://ollama.com/library) for the full list.

## See also

- [Troubleshooting](troubleshooting.md) — Ollama won't start, empty briefing
- [Deployment](deployment.md) — enabling the briefing in the manual stack
