#!/bin/sh
# Bundled Mosquitto: require a login when MOSQUITTO_USERNAME and
# MOSQUITTO_PASSWORD are set (setup generates them for new installs), stay
# anonymous otherwise so older .env files keep working.
set -eu

CONF="${MOSQUITTO_BASE_CONF:-/mosquitto/config/mosquitto.conf}"
RUNTIME_DIR="${MOSQUITTO_RUNTIME_DIR:-/tmp}"
RUNTIME_CONF="$RUNTIME_DIR/mosquitto.conf"
PASSWD="$RUNTIME_DIR/mosquitto.passwd"

cp "$CONF" "$RUNTIME_CONF"

if [ -n "${MOSQUITTO_USERNAME:-}" ] && [ -n "${MOSQUITTO_PASSWORD:-}" ]; then
    : >"$PASSWD"
    chmod 0700 "$PASSWD"
    mosquitto_passwd -b "$PASSWD" "$MOSQUITTO_USERNAME" "$MOSQUITTO_PASSWORD"
    chown mosquitto:mosquitto "$PASSWD" 2>/dev/null || true
    printf '\nallow_anonymous false\npassword_file %s\n' "$PASSWD" >>"$RUNTIME_CONF"
    echo "mosquitto: login required (user ${MOSQUITTO_USERNAME})"
else
    printf '\nallow_anonymous true\n' >>"$RUNTIME_CONF"
    echo "mosquitto: WARNING anonymous access - anyone who can reach port 1883 can read your health topics. Set MOSQUITTO_USERNAME and MOSQUITTO_PASSWORD in .env." >&2
fi

exec mosquitto -c "$RUNTIME_CONF"
