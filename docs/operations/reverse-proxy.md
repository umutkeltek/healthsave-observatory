# Reverse proxy

For any access beyond your LAN, put a reverse proxy in front of the API and terminate HTTPS there. The Observatory speaks plain HTTP on port 8000 internally; the proxy handles TLS and the public certificate.

> **Never expose plain HTTP to the internet.** If you need remote access, it must go through a reverse proxy that terminates HTTPS.

## Caddy example

Caddy is the simplest option — it provisions and renews certificates automatically. Add it to your Compose stack:

```yaml
# Add to docker-compose.yml
  caddy:
    image: caddy:2-alpine
    ports:
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
```

```
# Caddyfile
health.yourdomain.com {
    reverse_proxy api:8000
}
```

Point `health.yourdomain.com` at your server, bring the stack up, and Caddy fetches a certificate on first request. Then set the HealthSave app's Server URL to `https://health.yourdomain.com` (no port).

## Production posture

- Set a long random `API_KEY` in `.env` and in the HealthSave app.
- Keep TimescaleDB bound to localhost or a private Docker network — never publish 5432 to the internet.
- Terminate HTTPS at your reverse proxy; keep the API on plain HTTP behind it.
- Back up the `db_data` Docker volume regularly (see [Backups & migrations](backup-and-migrations.md)).
- Upgrade `TIMESCALE_IMAGE` and `GRAFANA_IMAGE` deliberately, pinned to a version — not via `latest`.
- If you expose Prometheus `/metrics`, protect it behind the same proxy (it is unauthenticated by design) — see [Metrics](metrics.md).

## See also

- [Deployment](deployment.md) — bringing the stack up and reaching it from your phone
- [Backups & migrations](backup-and-migrations.md) — protecting the data volume
- [Metrics](metrics.md) — protecting the unauthenticated scrape endpoint
