#!/usr/bin/env bash
#
# setup-local-ai.sh — one command to get a private, on-host LLM narrator.
#
# The "easy local" path (ADR-0003 D8): brings up the bundled Ollama sidecar
# (compose `local-ai` profile), pulls a model, and verifies it — so HealthSave
# Observatory's "Local" mode works with zero cloud egress and no external model
# server to install. Re-runnable; safe to run again to pull a different model.
#
# Usage:
#   deploy/local-ai/setup-local-ai.sh              # pulls the default model
#   MODEL=llama3.2:3b deploy/local-ai/setup-local-ai.sh   # smaller / faster on CPU
#
# After it finishes, open the Observatory → Intelligence → Local, or set
# LLM_PROVIDER=ollama in your .env. Nothing leaves your host in this mode.

set -euo pipefail

MODEL="${MODEL:-${OLLAMA_MODEL:-llama3.1:8b}}"
# Repo root = two levels up from this script (deploy/local-ai/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# docker compose v2 (plugin) or the legacy docker-compose binary.
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "error: docker compose not found. Install Docker Desktop or the compose plugin." >&2
  exit 1
fi

DC=("${COMPOSE[@]}" --profile local-ai)

echo "==> Starting the local-AI sidecar (Ollama, on-host, no cloud)…"
"${DC[@]}" up -d ollama

echo "==> Waiting for Ollama to be ready…"
for i in $(seq 1 60); do
  if "${DC[@]}" exec -T ollama ollama list >/dev/null 2>&1; then
    echo "    ready."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "error: Ollama did not become ready in time. Check: ${COMPOSE[*]} --profile local-ai logs ollama" >&2
    exit 1
  fi
  sleep 2
done

echo "==> Pulling model: ${MODEL}  (first run downloads a few GB; later runs are instant)…"
"${DC[@]}" exec -T ollama ollama pull "${MODEL}"

echo "==> Verifying the model answers…"
if "${DC[@]}" exec -T ollama ollama run "${MODEL}" "Reply with the single word: ready" >/dev/null 2>&1; then
  echo "    ✓ ${MODEL} responded."
else
  echo "    ⚠ Pull succeeded but the test generation failed — the model is installed; try it from the UI." >&2
fi

cat <<EOF

✓ Local AI is set up. The narrator can now run entirely on this host.

Next:
  • Open the Observatory → Intelligence → choose "Local", model "${MODEL}",
    then "Test connection" and "Save".
  • Or set in your .env:  LLM_PROVIDER=ollama  and  OLLAMA_MODEL=${MODEL}
    then restart:  ${COMPOSE[*]} up -d api worker

Privacy: in Local mode nothing leaves your host — no opt-in, no key, no cloud.
EOF
