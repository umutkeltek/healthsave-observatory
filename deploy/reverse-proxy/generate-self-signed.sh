#!/usr/bin/env bash
# Generate a 10-year self-signed TLS cert covering the LAN hostnames and IP.
# Runs on the operator's machine (not in a container) so the cert lives at a
# stable path the proxy override mounts read-only.
#
# Idempotent: skips generation if fullchain.pem already exists.
#
# Override the cert directory by exporting CERT_DIR before running, e.g.:
#   CERT_DIR=/srv/localappdata/health-data-hub/certs ./deploy/reverse-proxy/generate-self-signed.sh
set -euo pipefail

CERT_DIR="${CERT_DIR:-$(dirname "$0")/certs}"
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

if [ -f fullchain.pem ] && [ -f privkey.pem ]; then
  echo "Existing cert found at $CERT_DIR — skipping (delete to regenerate)."
  exit 0
fi

cat > openssl.cnf <<CNF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C  = TR
ST = Istanbul
L  = Istanbul
O  = HealthSave Observatory (homelab)
CN = apps-vm.internal

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = apps-vm.internal
DNS.2 = apps-vm
DNS.3 = apps-vm.local
DNS.4 = localhost
DNS.5 = observatory.local
IP.1  = 127.0.0.1
IP.2  = 192.168.33.123
CNF

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout privkey.pem \
  -out fullchain.pem \
  -days 3650 \
  -config openssl.cnf \
  -extensions v3_req >/dev/null 2>&1

chmod 600 privkey.pem
echo "Wrote:"
echo "  $CERT_DIR/fullchain.pem"
echo "  $CERT_DIR/privkey.pem"
openssl x509 -in fullchain.pem -noout -subject -dates
