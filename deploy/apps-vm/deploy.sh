#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_DIR="${REMOTE_DIR:-/srv/stacks/health-data-hub}"
REMOTE_ENV_DIR="${REMOTE_ENV_DIR:-/srv/localappdata/health-data-hub}"
DEPLOY_REF="${DEPLOY_REF:-HEAD}"
API_PORT="${API_PORT:-18080}"
GRAFANA_PORT="${GRAFANA_PORT:-3300}"
DB_PORT="${DB_PORT:-15432}"
PROJECT_NAME="${PROJECT_NAME:-health-data-hub}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -z "$REMOTE_HOST" ]; then
  cat >&2 <<'EOF'
REMOTE_HOST is required.

Example:
  REMOTE_HOST=your-vm.example ./deploy/apps-vm/deploy.sh
EOF
  exit 1
fi

cd "$PROJECT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "not a git repository: $PROJECT_DIR" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  cat >&2 <<'EOF'
refusing deploy from a dirty repository

commit or stash changes first, then rerun:
  git status
  git add -A
  git commit -m "..."
  ./deploy/apps-vm/deploy.sh
EOF
  exit 1
fi

COMMIT_SHA="$(git rev-parse "${DEPLOY_REF}^{commit}")"
BRANCH_NAME="$(git branch --show-current 2>/dev/null || true)"
[ -n "$BRANCH_NAME" ] || BRANCH_NAME="detached"
DEPLOYED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REMOTE_TMP="$(printf '%s' "$REMOTE_DIR.tmp.$COMMIT_SHA")"

ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "sudo mkdir -p '$REMOTE_DIR' '$REMOTE_ENV_DIR' && sudo chown -R debian:debian '$REMOTE_DIR' '$REMOTE_ENV_DIR'"
ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "rm -rf '$REMOTE_TMP' && mkdir -p '$REMOTE_TMP'"

git archive --format=tar "$COMMIT_SHA" \
  | gzip -c \
  | ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "tar xzf - -C '$REMOTE_TMP'"

ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "sudo bash -lc '
set -euo pipefail
if [ ! -f \"$REMOTE_ENV_DIR/.env\" ]; then
  DB_PASSWORD=\$(openssl rand -hex 24)
  API_KEY=\$(openssl rand -hex 24)
  GRAFANA_PASSWORD=\$(openssl rand -hex 24)
  cat > \"$REMOTE_ENV_DIR/.env\" <<EOF
DB_PASSWORD=\$DB_PASSWORD
API_KEY=\$API_KEY
GRAFANA_PASSWORD=\$GRAFANA_PASSWORD
LLM_PROVIDER=disabled
LLM_BASE_URL=
OLLAMA_MODEL=
LLM_API_KEY=
HA_MQTT_ENABLED=false
HEALTH_DATA_HUB_API_PORT=$API_PORT
HEALTH_DATA_HUB_GRAFANA_PORT=$GRAFANA_PORT
HEALTH_DATA_HUB_DB_PORT=$DB_PORT
EOF
  chmod 600 \"$REMOTE_ENV_DIR/.env\"
fi
find \"$REMOTE_DIR\" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a \"$REMOTE_TMP\"/. \"$REMOTE_DIR\"/
rm -rf \"$REMOTE_TMP\"
cd \"$REMOTE_DIR\"
ln -sf \"$REMOTE_ENV_DIR/.env\" .env
cat > docker-compose.apps-vm.override.yml <<EOF
services:
  db:
    ports: !override
      - \"127.0.0.1:\${HEALTH_DATA_HUB_DB_PORT:-$DB_PORT}:5432\"
  api:
    ports: !override
      - \"\${HEALTH_DATA_HUB_API_PORT:-$API_PORT}:8000\"
  grafana:
    ports: !override
      - \"\${HEALTH_DATA_HUB_GRAFANA_PORT:-$GRAFANA_PORT}:3000\"
EOF
docker compose --env-file \"$REMOTE_ENV_DIR/.env\" \
  -f docker-compose.yml \
  -f docker-compose.apps-vm.override.yml \
  -p "$PROJECT_NAME" \
  up -d --build db api grafana
cat > \"$REMOTE_ENV_DIR/current-release.env\" <<EOF
APP=health-data-hub
DEPLOY_REF=$DEPLOY_REF
COMMIT_SHA=$COMMIT_SHA
BRANCH=$BRANCH_NAME
DEPLOYED_AT=$DEPLOYED_AT
REMOTE_DIR=$REMOTE_DIR
API_PORT=$API_PORT
GRAFANA_PORT=$GRAFANA_PORT
DB_PORT=$DB_PORT
EOF
'"

echo "health-data-hub deployed to $REMOTE_HOST:$REMOTE_DIR"
echo "commit: $COMMIT_SHA"
echo "api: http://$REMOTE_HOST:$API_PORT"
echo "grafana: http://$REMOTE_HOST:$GRAFANA_PORT"
