# Reverse proxy — durable per-IP rate limiting (SECURITY-004)

The API ships in-process safety caps (16 MiB body, 50k-sample batch, 100k export
clamp), but those are **per-request**, not per-IP, and can't throttle an abusive
client. For any **internet-facing** deploy, put this nginx reverse proxy in front:
it adds **durable per-IP rate limiting** at the gateway and gives you one
TLS-capable ingress, so the API itself is never published on the host.

## What it does

- Per-IP rate limits via `limit_req_zone` (state survives restarts):
  - general API: `10 r/s`, burst 20
  - ingest + Whoop webhook: `2 r/s`, tighter burst
  - liveness/readiness probes: **never** limited
- Per-IP connection cap, `429` on limit breach.
- Body size capped at 16 MiB (matches the app).
- Optional TLS termination (or front it with Cloudflare / an external LB).

## Use it (base compose)

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/reverse-proxy/docker-compose.proxy.override.yml \
  up -d
```

The override **removes the API's host port publish** (`ports: !override []`) and
exposes only the proxy on `:80` (set `PROXY_HTTP_PORT` to change). The API is then
reachable only on the internal compose network, via the proxy.

## TLS

Two supported paths:

1. **Terminate at nginx:** mount certs and uncomment the `:443` block in
   `nginx.conf` + the `443` mapping + the `certs` volume in the override. Switch
   the `:80` server to `return 301 https://$host$request_uri;`. Provision certs
   with your tool of choice (certbot/Let's Encrypt, etc.).
2. **Terminate upstream:** keep plain `:80` and front it with Cloudflare
   (full/strict) or an external load balancer. Uncomment the `real_ip` block in
   `nginx.conf` and set your proxy's CIDR so rate limits key on the real client
   IP, not the upstream.

## Remote-VM flow

`deploy/remote-vm/deploy.sh` generates its own override that publishes the API on
`${API_PORT}` (default 18080) on all interfaces. To put this proxy in front there,
layer it **last** so its `ports: !override []` wins:

```bash
docker compose --env-file "$REMOTE_ENV_DIR/.env" \
  -f docker-compose.yml \
  -f docker-compose.remote-vm.override.yml \
  -f deploy/reverse-proxy/docker-compose.proxy.override.yml \
  -p health-data-hub up -d
```

`deploy.sh` is intentionally not modified (it must never re-mint secrets on
redeploy). Adopting the proxy in the remote flow is an explicit operator step.

## Tuning

Rate limits live in `nginx.conf` (`limit_req_zone ... rate=`). A single iOS
device bursts on sync, so `burst` is generous on `/api/apple/batch`; tighten the
general `api` zone if you expose more surface. The egress trust boundary is
unaffected — this is ingress only.
