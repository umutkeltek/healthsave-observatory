#!/usr/bin/env bash
#
# Health Data Hub - one-command bootstrap for non-technical users.
#
# Usage:
#   ./setup.sh            # interactive setup
#   ./setup.sh doctor     # post-install health checks
#   ./setup.sh --help     # show usage
#
# Designed to be idempotent: re-running preserves existing passwords and
# updates only AI-related config based on the setup answers.

set -euo pipefail

# ---------------------------------------------------------------- logging
if [ -t 1 ]; then
    COLOR_RESET="$(printf '\033[0m')"
    COLOR_INFO="$(printf '\033[1;34m')"
    COLOR_WARN="$(printf '\033[1;33m')"
    COLOR_ERR="$(printf '\033[1;31m')"
    COLOR_OK="$(printf '\033[1;32m')"
else
    COLOR_RESET=""
    COLOR_INFO=""
    COLOR_WARN=""
    COLOR_ERR=""
    COLOR_OK=""
fi

log_info()  { printf '%s[INFO]%s %s\n' "$COLOR_INFO" "$COLOR_RESET" "$*"; }
log_warn()  { printf '%s[WARN]%s %s\n' "$COLOR_WARN" "$COLOR_RESET" "$*" >&2; }
log_error() { printf '%s[ERR]%s  %s\n' "$COLOR_ERR"  "$COLOR_RESET" "$*" >&2; }
log_ok()    { printf '%s[OK]%s   %s\n' "$COLOR_OK"   "$COLOR_RESET" "$*"; }

# -------------------------------------------------------------- constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"
CONFIG_FILE="config.yaml"
CONFIG_EXAMPLE="config.yaml.example"
COMPOSE_OVERRIDE="docker-compose.override.yml"
COMPOSE_OVERRIDE_EXAMPLE="docker-compose.override.yml.example"

API_URL_DEFAULT="http://localhost:8000"
GRAFANA_URL_DEFAULT="http://localhost:3000"
OLLAMA_URL_DEFAULT="http://localhost:11434"

# ----------------------------------------------------------------- helpers
print_usage() {
    cat <<'EOF'
Health Data Hub bootstrap.

Usage:
  ./setup.sh            Run interactive setup (default).
  ./setup.sh setup      Same as ./setup.sh with no args.
  ./setup.sh doctor     Run post-install health checks against
                        the running stack.
  ./setup.sh --help     Show this message.
  ./setup.sh -h         Show this message.
EOF
}

rand_hex() {
    # 32-char hex string. Prefer openssl; fall back to /dev/urandom.
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 16
    else
        head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

detect_lan_ip() {
    local ip=""
    case "$(uname -s)" in
        Darwin)
            ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
            if [ -z "$ip" ]; then
                ip="$(ipconfig getifaddr en1 2>/dev/null || true)"
            fi
            ;;
        Linux)
            if command -v hostname >/dev/null 2>&1; then
                ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
            fi
            ;;
    esac
    if [ -z "$ip" ]; then
        ip="your-host-ip"
    fi
    printf '%s' "$ip"
}

# ---------------------------------------------------------------- hardware
# Pure functions - each writes one line to stdout, reads no globals, so
# they can be sourced directly in unit tests.
detect_ram_gb() {
    local bytes kb
    case "$(uname -s)" in
        Darwin)
            bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
            if [ -n "$bytes" ] && [ "$bytes" -gt 0 ] 2>/dev/null; then
                echo $(( bytes / 1024 / 1024 / 1024 ))
                return
            fi
            ;;
        Linux)
            if [ -r /proc/meminfo ]; then
                kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)"
                if [ -n "$kb" ] && [ "$kb" -gt 0 ] 2>/dev/null; then
                    echo $(( kb / 1024 / 1024 ))
                    return
                fi
            fi
            ;;
    esac
    # Fallback: conservative 16 GB assumption (D3).
    echo 16
}

detect_gpu_kind() {
    local os
    os="$(uname -s)"

    if [ "$os" = "Darwin" ]; then
        # Intel Mac → none: Ollama Metal backend is Apple-Silicon only (D8).
        if [ "$(uname -m)" = "arm64" ]; then
            echo apple_silicon
        else
            echo none
        fi
        return
    fi

    # Linux (and WSL2 which reports as Linux).
    if command -v nvidia-smi >/dev/null 2>&1; then
        if timeout 2s nvidia-smi --version >/dev/null 2>&1; then
            echo nvidia
            return
        fi
    fi
    if command -v lspci >/dev/null 2>&1; then
        if lspci 2>/dev/null | grep -iE 'vga|3d|display' | grep -iE 'amd|radeon|advanced micro' >/dev/null 2>&1; then
            echo amd
            return
        fi
    fi
    echo none
}

recommend_model() {
    local ram_gb="$1"
    local gpu_kind="$2"
    # Guard non-integer input - fall back to the safe default.
    if ! [[ "$ram_gb" =~ ^[0-9]+$ ]]; then
        echo llama3.2:3b
        return
    fi

    if [ "$ram_gb" -lt 6 ]; then
        echo SKIP
        return
    fi

    case "$gpu_kind" in
        nvidia)
            if   [ "$ram_gb" -lt 10 ]; then echo llama3.2:3b
            elif [ "$ram_gb" -lt 18 ]; then echo llama3.1:8b
            elif [ "$ram_gb" -lt 36 ]; then echo llama3.1:8b
            elif [ "$ram_gb" -lt 96 ]; then echo qwen2.5:14b
            else                            echo llama3.1:70b
            fi
            ;;
        *)
            if   [ "$ram_gb" -lt 10 ]; then echo llama3.2:1b
            elif [ "$ram_gb" -lt 18 ]; then echo llama3.2:3b
            elif [ "$ram_gb" -lt 36 ]; then echo llama3.1:8b
            elif [ "$ram_gb" -lt 96 ]; then echo llama3.1:8b
            else                            echo qwen2.5:32b
            fi
            ;;
    esac
}

describe_gpu_kind() {
    case "$1" in
        apple_silicon) echo 'Apple Silicon GPU (unified memory)' ;;
        nvidia)        echo 'NVIDIA GPU (CUDA)' ;;
        amd)           echo 'AMD GPU' ;;
        *)             echo 'no dedicated GPU' ;;
    esac
}

describe_model_size() {
    case "$1" in
        llama3.2:1b)   echo '~1.3 GB resident, fast, lower quality' ;;
        llama3.2:3b)   echo '~2 GB, decent narrative' ;;
        llama3.1:8b)   echo '~4.7 GB, good narrative quality' ;;
        qwen2.5:14b)   echo '~9 GB, strong narrative on dGPU' ;;
        qwen2.5:32b)   echo '~20 GB, large model - rich narrative' ;;
        llama3.1:70b)  echo '~40 GB, premium quality on big hardware' ;;
        *)             echo 'custom model tag' ;;
    esac
}

docker_available() {
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

compose() {
    docker compose "$@"
}

prompt_default() {
    # prompt_default <prompt> <default> -> value
    local prompt="$1"
    local default_value="$2"
    local answer=""
    if [ -t 0 ]; then
        printf '%s [%s]: ' "$prompt" "$default_value"
        read -r answer || answer=""
    fi
    if [ -z "$answer" ]; then
        printf '%s' "$default_value"
    else
        printf '%s' "$answer"
    fi
}

prompt_yes_no() {
    # prompt_yes_no <prompt> <default y|N> -> returns 0 for yes
    local prompt="$1"
    local default="$2"
    local answer=""
    if [ -t 0 ]; then
        printf '%s [%s]: ' "$prompt" "$default"
        read -r answer || answer=""
    fi
    if [ -z "$answer" ]; then
        answer="$default"
    fi
    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

write_env_file() {
    local db_password="$1"
    local grafana_password="$2"
    local api_key="$3"
    cat >"$ENV_FILE" <<EOF
DB_PASSWORD=${db_password}
GRAFANA_PASSWORD=${grafana_password}

# Optional: set an API key to require X-API-Key header on requests
# Leave empty to allow unauthenticated access (fine if behind VPN/firewall)
API_KEY=${api_key}

# Optional image pins. Override only when deliberately upgrading.
TIMESCALE_IMAGE=timescale/timescaledb:2.17.2-pg16
GRAFANA_IMAGE=grafana/grafana-oss:11.2.0

# LLM provider for the Phase 1 AI analysis engine. The local-first
# default runs fully on-device via Ollama - no data ever leaves the
# Docker network. Change these only if you explicitly want to use a
# cloud provider (in which case also set the provider's api_key in
# config.yaml).
LLM_PROVIDER=ollama
LLM_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b

# setup.sh creates config.yaml and keeps Compose pointed at it.
# Manual docker compose users can keep .env.example's config.yaml.example.
ANALYSIS_CONFIG_FILE=./config.yaml
EOF
    chmod 600 "$ENV_FILE" 2>/dev/null || true
}

read_env_value() {
    # read_env_value <KEY> - first matching value from .env, empty if absent.
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d= -f2 || true
}

set_env_model() {
    # Update OLLAMA_MODEL=<tag> in .env. Portable sed (BSD + GNU) via -i.bak.
    local model_tag="$1"
    [ -z "$model_tag" ] && return 0
    [ ! -f "$ENV_FILE" ] && return 0
    if grep -q '^OLLAMA_MODEL=' "$ENV_FILE" 2>/dev/null; then
        sed -i.bak "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=${model_tag}|" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
    else
        printf 'OLLAMA_MODEL=%s\n' "$model_tag" >>"$ENV_FILE"
    fi
}

ensure_env_value() {
    # ensure_env_value <KEY> <VALUE> - add or replace KEY in .env.
    local key="$1"
    local value="$2"
    [ ! -f "$ENV_FILE" ] && return 0
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
    else
        printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
    fi
}

set_config_daily_briefing_enabled() {
    # set_config_daily_briefing_enabled true|false
    local enabled="$1"
    [ ! -f "$CONFIG_FILE" ] && return 0
    local tmp="${CONFIG_FILE}.tmp.$$"
    awk -v enabled="$enabled" '
        BEGIN { in_analysis = 0; in_daily = 0 }
        /^analysis:/ { in_analysis = 1; in_daily = 0; print; next }
        /^[^[:space:]][^:]*:/ {
            if ($0 !~ /^analysis:/) { in_analysis = 0; in_daily = 0 }
        }
        in_analysis && /^  daily_briefing:/ { in_daily = 1; print; next }
        in_analysis && /^  [A-Za-z_][A-Za-z_]*:/ && $1 != "daily_briefing:" {
            in_daily = 0
        }
        in_daily && /^    enabled:/ {
            sub(/enabled:.*/, "enabled: " enabled)
            print
            next
        }
        { print }
    ' "$CONFIG_FILE" >"$tmp"
    mv "$tmp" "$CONFIG_FILE"
}

set_config_anomaly_detection_enabled() {
    # set_config_anomaly_detection_enabled true|false
    local enabled="$1"
    [ ! -f "$CONFIG_FILE" ] && return 0
    local tmp="${CONFIG_FILE}.tmp.$$"
    awk -v enabled="$enabled" '
        BEGIN { in_analysis = 0; in_anomaly = 0 }
        /^analysis:/ { in_analysis = 1; in_anomaly = 0; print; next }
        /^[^[:space:]][^:]*:/ {
            if ($0 !~ /^analysis:/) { in_analysis = 0; in_anomaly = 0 }
        }
        in_analysis && /^  anomaly_detection:/ { in_anomaly = 1; print; next }
        in_analysis && /^  [A-Za-z_][A-Za-z_]*:/ && $1 != "anomaly_detection:" {
            in_anomaly = 0
        }
        in_anomaly && /^    enabled:/ {
            sub(/enabled:.*/, "enabled: " enabled)
            print
            next
        }
        { print }
    ' "$CONFIG_FILE" >"$tmp"
    mv "$tmp" "$CONFIG_FILE"
}

set_config_llm_model() {
    # set_config_llm_model <ollama-model-tag>
    local model_tag="$1"
    [ -z "$model_tag" ] && return 0
    [ ! -f "$CONFIG_FILE" ] && return 0
    local tmp="${CONFIG_FILE}.tmp.$$"
    awk -v model="$model_tag" '
        BEGIN { in_llm = 0 }
        /^llm:/ { in_llm = 1; print; next }
        /^[^[:space:]][^:]*:/ {
            if ($0 !~ /^llm:/) { in_llm = 0 }
        }
        in_llm && /^  model:/ {
            sub(/model:.*/, "model: \"" model "\"")
            print
            next
        }
        { print }
    ' "$CONFIG_FILE" >"$tmp"
    mv "$tmp" "$CONFIG_FILE"
}

wait_for_ollama() {
    # Wait up to 120s for the Ollama HTTP API to accept requests.
    local max_attempts=40
    local attempt=0
    while [ "$attempt" -lt "$max_attempts" ]; do
        if curl -fsS "${OLLAMA_URL_DEFAULT}/" >/dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 3
    done
    return 1
}

check_endpoint() {
    # check_endpoint <label> <url>
    local label="$1"
    local url="$2"
    if curl -fsS "$url" >/dev/null 2>&1; then
        log_ok "${label}: ${url} reachable"
        return 0
    fi
    log_error "${label}: ${url} NOT reachable"
    return 1
}

# ------------------------------------------------------------------ setup
cmd_setup() {
    log_info "Health Data Hub bootstrap - self-hosted setup"

    if ! docker_available; then
        log_error "Docker is not running. Start Docker Desktop (or the Docker daemon) and re-run ./setup.sh."
        exit 1
    fi

    # --- .env (preserve if present) -------------------------------------
    if [ -f "$ENV_FILE" ]; then
        log_warn "$ENV_FILE already exists - keeping the existing values."
    else
        if [ ! -f "$ENV_EXAMPLE" ]; then
            log_error "$ENV_EXAMPLE is missing - cannot generate $ENV_FILE."
            exit 1
        fi
        local generated_db_pw
        generated_db_pw="$(rand_hex)"
        local generated_grafana_pw
        generated_grafana_pw="$(rand_hex)"
        local api_key_default=""

        local db_pw grafana_pw api_key
        db_pw="$(prompt_default 'Database password' "$generated_db_pw")"
        grafana_pw="$(prompt_default 'Grafana admin password' "$generated_grafana_pw")"
        api_key="$(prompt_default 'API key for X-API-Key header (leave empty for open access)' "$api_key_default")"

        write_env_file "$db_pw" "$grafana_pw" "$api_key"
        log_ok "Wrote $ENV_FILE"
    fi

    # --- config.yaml (preserve if present) ------------------------------
    if [ -f "$CONFIG_FILE" ]; then
        log_warn "$CONFIG_FILE already exists - keeping the existing values."
    else
        if [ ! -f "$CONFIG_EXAMPLE" ]; then
            log_error "$CONFIG_EXAMPLE is missing - cannot generate $CONFIG_FILE."
            exit 1
        fi
        cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
        log_ok "Wrote $CONFIG_FILE from $CONFIG_EXAMPLE"
    fi

    # --- Ollama opt-in --------------------------------------------------
    local enable_ollama=0
    if prompt_yes_no 'Enable local LLM (Ollama) for AI analysis?' 'y/N'; then
        enable_ollama=1
    fi

    local OLLAMA_MODEL_CHOICE=""
    if [ "$enable_ollama" -eq 1 ]; then
        local ram_gb gpu_kind gpu_label recommended size_hint
        ram_gb="$(detect_ram_gb)"
        gpu_kind="$(detect_gpu_kind)"
        gpu_label="$(describe_gpu_kind "$gpu_kind")"
        recommended="$(recommend_model "$ram_gb" "$gpu_kind")"

        if [ "$recommended" = "SKIP" ]; then
            log_warn "Detected: ${ram_gb} GB RAM, ${gpu_label}."
            log_warn "Your system has less than 6 GB RAM. AI features won't run reliably. Skipping Ollama setup."
            enable_ollama=0
        else
            size_hint="$(describe_model_size "$recommended")"
            log_info "Detected: ${ram_gb} GB RAM, ${gpu_label}."
            log_info "Recommended model: ${recommended} (${size_hint})"
            log_info "Press Enter to accept, or type a different tag (e.g. llama3.2:3b)."
            OLLAMA_MODEL_CHOICE="$(prompt_default 'Ollama model' "$recommended")"
            log_info "Using Ollama model: ${OLLAMA_MODEL_CHOICE}"
        fi
    fi

    if [ "$enable_ollama" -eq 1 ]; then
        if [ -f "$COMPOSE_OVERRIDE" ]; then
            log_warn "$COMPOSE_OVERRIDE already exists - leaving it as-is."
        else
            if [ ! -f "$COMPOSE_OVERRIDE_EXAMPLE" ]; then
                log_error "$COMPOSE_OVERRIDE_EXAMPLE is missing - cannot enable Ollama."
                exit 1
            fi
            cp "$COMPOSE_OVERRIDE_EXAMPLE" "$COMPOSE_OVERRIDE"
            log_ok "Copied $COMPOSE_OVERRIDE_EXAMPLE → $COMPOSE_OVERRIDE"
        fi
        # Persist the chosen model into .env so direct-compose runs and
        # pull_model below both pick it up.
        if [ -n "${OLLAMA_MODEL_CHOICE:-}" ]; then
            set_env_model "$OLLAMA_MODEL_CHOICE"
            log_ok "Set OLLAMA_MODEL=${OLLAMA_MODEL_CHOICE} in $ENV_FILE"
        fi
    else
        log_info "Skipping Ollama. The stack will run without a local LLM."
    fi

    ensure_env_value "ANALYSIS_CONFIG_FILE" "./config.yaml"
    if [ "$enable_ollama" -eq 1 ]; then
        set_config_daily_briefing_enabled true
        set_config_anomaly_detection_enabled true
        if [ -n "${OLLAMA_MODEL_CHOICE:-}" ]; then
            set_config_llm_model "$OLLAMA_MODEL_CHOICE"
        fi
    else
        set_config_daily_briefing_enabled false
        set_config_anomaly_detection_enabled false
    fi

    # --- bring the stack up --------------------------------------------
    log_info "Starting Docker services (this may take a few minutes on first run)..."
    compose up -d

    # --- pull the Ollama model, if opted in ----------------------------
    if [ "$enable_ollama" -eq 1 ]; then
        log_info "Waiting for Ollama to become ready on ${OLLAMA_URL_DEFAULT}..."
        if ! wait_for_ollama; then
            log_error "Ollama did not become ready within 120 seconds. Check 'docker compose logs ollama'."
            exit 1
        fi
        # Prefer the in-process choice so we don't re-parse .env right after
        # writing it; fall back to .env, then to the proven 8b default.
        local model_name="${OLLAMA_MODEL_CHOICE:-}"
        if [ -z "$model_name" ]; then
            model_name="$(read_env_value OLLAMA_MODEL)"
        fi
        if [ -z "$model_name" ]; then
            model_name="llama3.1:8b"
        fi
        log_info "Pulling Ollama model '${model_name}' (streaming progress)..."
        compose exec -T ollama ollama pull "$model_name"
        log_ok "Ollama model '${model_name}' is ready."
    fi

    # --- final summary --------------------------------------------------
    local lan_ip
    lan_ip="$(detect_lan_ip)"
    local grafana_user="admin"
    local grafana_pw
    grafana_pw="$(read_env_value GRAFANA_PASSWORD)"

    echo
    log_ok "Health Data Hub is up."
    echo "  API:            ${API_URL_DEFAULT}"
    echo "  Readiness:      ${API_URL_DEFAULT}/ready"
    echo "  Grafana:        ${GRAFANA_URL_DEFAULT}  (user: ${grafana_user}, pass: ${grafana_pw})"
    echo "  iOS app URL:    http://${lan_ip}:8000"
    echo
    log_info "Next step: ./setup.sh doctor   - verify every service is healthy."
}

# ------------------------------------------------------------------ doctor
cmd_doctor() {
    log_info "Running post-install health checks..."
    local failures=0

    if ! docker_available; then
        log_error "Docker is not running - cannot continue."
        exit 1
    fi

    # --- compose services ----------------------------------------------
    local ps_output
    ps_output="$(compose ps --format '{{.Service}} {{.State}}' 2>/dev/null || true)"
    if [ -z "$ps_output" ]; then
        log_error "docker compose ps returned no services. Did you run ./setup.sh first?"
        exit 1
    fi

    while IFS=' ' read -r svc state; do
        [ -z "${svc:-}" ] && continue
        if [ "${state:-}" = "running" ]; then
            log_ok "service ${svc}: running"
        else
            log_error "service ${svc}: ${state:-unknown}"
            failures=$((failures + 1))
        fi
    done <<<"$ps_output"

    # --- API endpoints --------------------------------------------------
    check_endpoint "API /health" "${API_URL_DEFAULT}/health" || failures=$((failures + 1))
    check_endpoint "API /ready"  "${API_URL_DEFAULT}/ready"  || failures=$((failures + 1))

    # --- Ollama (only if enabled) --------------------------------------
    if [ -f "$COMPOSE_OVERRIDE" ]; then
        if ! check_endpoint "Ollama /api/tags" "${OLLAMA_URL_DEFAULT}/api/tags"; then
            failures=$((failures + 1))
        fi

        # Configured model + pulled-status line. Best-effort - never fails
        # the doctor since model presence is informational, not gating.
        local configured_model pulled_marker list_output
        configured_model="$(read_env_value OLLAMA_MODEL)"
        if [ -z "$configured_model" ]; then
            configured_model="llama3.1:8b"
        fi
        pulled_marker="?"
        if list_output="$(compose exec -T ollama ollama list 2>/dev/null)"; then
            if printf '%s' "$list_output" | grep -iF "$configured_model" >/dev/null 2>&1; then
                pulled_marker="✓"
            else
                pulled_marker="✗"
            fi
        fi
        log_info "Configured model: ${configured_model}    Pulled: ${pulled_marker}"
    else
        log_info "Configured model: (Ollama disabled)"
    fi

    echo
    if [ "$failures" -gt 0 ]; then
        log_error "Doctor found ${failures} issue(s). Run 'docker compose logs' on any failing service to investigate."
        exit 1
    fi
    log_ok "All checks passed."
}

# --------------------------------------------------------------- dispatch
if [ "${HEALTHSAVE_SETUP_TEST:-0}" != "1" ]; then
    cmd="${1:-setup}"
    case "$cmd" in
        setup|"")     cmd_setup ;;
        doctor)       cmd_doctor ;;
        --help|-h|help) print_usage ;;
        *)
            log_error "Unknown command: ${cmd}"
            print_usage
            exit 2
            ;;
    esac
fi
