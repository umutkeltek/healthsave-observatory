#!/usr/bin/env bash
#
# Health Data Hub — one-command bootstrap for non-technical users.
#
# Usage:
#   ./setup.sh            # interactive setup
#   ./setup.sh doctor     # post-install health checks
#   ./setup.sh --help     # show usage
#
# Designed to be idempotent: re-running preserves an existing .env /
# config.yaml and just re-validates the stack.

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
# default runs fully on-device via Ollama — no data ever leaves the
# Docker network. Change these only if you explicitly want to use a
# cloud provider (in which case also set the provider's api_key in
# config.yaml).
LLM_PROVIDER=ollama
LLM_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b
EOF
    chmod 600 "$ENV_FILE" 2>/dev/null || true
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
    log_info "Health Data Hub bootstrap — self-hosted setup"

    if ! docker_available; then
        log_error "Docker is not running. Start Docker Desktop (or the Docker daemon) and re-run ./setup.sh."
        exit 1
    fi

    # --- .env (preserve if present) -------------------------------------
    if [ -f "$ENV_FILE" ]; then
        log_warn "$ENV_FILE already exists — keeping the existing values."
    else
        if [ ! -f "$ENV_EXAMPLE" ]; then
            log_error "$ENV_EXAMPLE is missing — cannot generate $ENV_FILE."
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
        log_warn "$CONFIG_FILE already exists — keeping the existing values."
    else
        if [ ! -f "$CONFIG_EXAMPLE" ]; then
            log_error "$CONFIG_EXAMPLE is missing — cannot generate $CONFIG_FILE."
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

    if [ "$enable_ollama" -eq 1 ]; then
        if [ -f "$COMPOSE_OVERRIDE" ]; then
            log_warn "$COMPOSE_OVERRIDE already exists — leaving it as-is."
        else
            if [ ! -f "$COMPOSE_OVERRIDE_EXAMPLE" ]; then
                log_error "$COMPOSE_OVERRIDE_EXAMPLE is missing — cannot enable Ollama."
                exit 1
            fi
            cp "$COMPOSE_OVERRIDE_EXAMPLE" "$COMPOSE_OVERRIDE"
            log_ok "Copied $COMPOSE_OVERRIDE_EXAMPLE → $COMPOSE_OVERRIDE"
        fi
    else
        log_info "Skipping Ollama. The stack will run without a local LLM."
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
        # shellcheck disable=SC1091
        local model_name
        model_name="$(grep -E '^OLLAMA_MODEL=' "$ENV_FILE" | head -n 1 | cut -d= -f2 || true)"
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
    grafana_pw="$(grep -E '^GRAFANA_PASSWORD=' "$ENV_FILE" | head -n 1 | cut -d= -f2 || true)"

    echo
    log_ok "Health Data Hub is up."
    echo "  API:            ${API_URL_DEFAULT}"
    echo "  Readiness:      ${API_URL_DEFAULT}/ready"
    echo "  Grafana:        ${GRAFANA_URL_DEFAULT}  (user: ${grafana_user}, pass: ${grafana_pw})"
    echo "  iOS app URL:    http://${lan_ip}:8000"
    echo
    log_info "Next step: ./setup.sh doctor   — verify every service is healthy."
}

# ------------------------------------------------------------------ doctor
cmd_doctor() {
    log_info "Running post-install health checks..."
    local failures=0

    if ! docker_available; then
        log_error "Docker is not running — cannot continue."
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
    fi

    echo
    if [ "$failures" -gt 0 ]; then
        log_error "Doctor found ${failures} issue(s). Run 'docker compose logs' on any failing service to investigate."
        exit 1
    fi
    log_ok "All checks passed."
}

# --------------------------------------------------------------- dispatch
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
