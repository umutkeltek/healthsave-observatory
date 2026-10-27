#!/usr/bin/env bash
# Generate a 10-year self-signed TLS cert for the hostnames and IPs your phone
# and browser use to reach this machine. Runs on the operator's machine (not in
# a container) so the cert lives at a stable path the proxy override mounts
# read-only.
#
# Idempotent: skips generation if fullchain.pem already exists.
#
#   CERT_HOSTNAMES  space-separated DNS names (default: this host's name + localhost)
#   CERT_IPS        space-separated IPs (default: 127.0.0.1)
#   CERT_DIR        output directory (default: deploy/reverse-proxy/certs)
#
# Example:
#   CERT_HOSTNAMES="observatory.lan observatory" CERT_IPS="127.0.0.1 192.168.1.20" \
#     ./deploy/reverse-proxy/generate-self-signed.sh
set -euo pipefail

CERT_DIR="${CERT_DIR:-$(dirname "$0")/certs}"
CERT_HOSTNAMES="${CERT_HOSTNAMES:-$(hostname) localhost}"
CERT_IPS="${CERT_IPS:-127.0.0.1}"
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

if [ -f fullchain.pem ] && [ -f privkey.pem ]; then
  echo "Existing cert found at $CERT_DIR — skipping (delete to regenerate)."
  exit 0
fi

read -r -a hostnames <<<"$CERT_HOSTNAMES"
read -r -a ips <<<"$CERT_IPS"
if [ "${#hostnames[@]}" -eq 0 ]; then
  echo "CERT_HOSTNAMES is empty; set at least one name." >&2
  exit 2
fi

{
  cat <<CNF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
O  = HealthSave Observatory (self-signed)
CN = ${hostnames[0]}

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
CNF
  for i in "${!hostnames[@]}"; do
    printf 'DNS.%d = %s\n' "$((i + 1))" "${hostnames[$i]}"
  done
  for i in "${!ips[@]}"; do
    printf 'IP.%d = %s\n' "$((i + 1))" "${ips[$i]}"
  done
} > openssl.cnf

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
