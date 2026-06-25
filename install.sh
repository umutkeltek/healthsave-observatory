#!/usr/bin/env sh
set -eu

REPO_URL="${HEALTHSAVE_OBSERVATORY_REPO:-https://github.com/umutkeltek/healthsave-observatory.git}"
TARBALL_URL="${HEALTHSAVE_OBSERVATORY_TARBALL:-https://github.com/umutkeltek/healthsave-observatory/archive/refs/heads/main.tar.gz}"
TARGET_DIR="${HEALTHSAVE_OBSERVATORY_HOME:-${HOME:-$(pwd)}/healthsave-observatory}"

info() {
  printf '[INFO] %s\n' "$*" >&2
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

fail() {
  printf '[ERR] %s\n' "$*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

is_termux() {
  [ -n "${TERMUX_VERSION:-}" ] || printf '%s' "${PREFIX:-}" | grep -q '/com.termux/'
}

is_wsl() {
  [ -r /proc/version ] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}

restore_tty_stdin() {
  # curl | sh consumes stdin; interactive TUI needs the real terminal.
  if [ -r /dev/tty ]; then
    exec </dev/tty
  fi
}

check_platform() {
  if is_termux; then
    fail "Termux is not supported because HealthSave Observatory needs Docker Compose. Use Linux, macOS, or Windows with WSL2 + Docker Desktop WSL integration."
  fi

  if ! have docker; then
    if is_wsl; then
      fail "Docker CLI not found in WSL2. Install Docker Desktop, enable WSL integration for this distro, then rerun this installer."
    fi
    fail "Docker is required. Install Docker Desktop or Docker Engine, start it, then rerun this installer."
  fi

  if ! docker compose version >/dev/null 2>&1; then
    fail "Docker Compose v2 is required. Install or update Docker Desktop/Docker Engine so 'docker compose version' works."
  fi
}

is_checkout() {
  [ -x "$1/healthsave" ] && [ -f "$1/setup.sh" ] && [ -f "$1/docker-compose.yml" ]
}

ensure_checkout() {
  if is_checkout "$TARGET_DIR"; then
    return 0
  fi

  if [ -e "$TARGET_DIR" ] && [ "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; then
    fail "$TARGET_DIR exists but is not a HealthSave Observatory checkout. Set HEALTHSAVE_OBSERVATORY_HOME to an empty directory or existing checkout."
  fi

  mkdir -p "$(dirname "$TARGET_DIR")"

  if have git; then
    info "Cloning HealthSave Observatory into $TARGET_DIR"
    git clone "$REPO_URL" "$TARGET_DIR"
    return 0
  fi

  have curl || fail "git is missing and curl is not available for tarball fallback."
  have tar || fail "git is missing and tar is not available for tarball fallback."

  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
  mkdir -p "$TARGET_DIR"
  info "Downloading HealthSave Observatory into $TARGET_DIR"
  curl -fsSL "$TARBALL_URL" -o "$tmp_dir/healthsave-observatory.tar.gz"
  tar -xzf "$tmp_dir/healthsave-observatory.tar.gz" -C "$TARGET_DIR" --strip-components=1
}

launch_checkout() {
  ensure_checkout
  if ! is_checkout "$TARGET_DIR"; then
    fail "$TARGET_DIR does not contain a usable HealthSave Observatory checkout after download."
  fi

  if "$TARGET_DIR/healthsave" install-cli >/dev/null 2>&1; then
    info "Installed local 'healthsave' wrapper when possible."
  else
    warn "Could not install local 'healthsave' wrapper; continuing with repo-local launcher."
  fi

  restore_tty_stdin
  exec "$TARGET_DIR/healthsave" onboard
}

main() {
  check_platform
  info "HealthSave Observatory guided installer"
  launch_checkout
}

main "$@"
