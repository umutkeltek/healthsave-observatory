# apps-vm deployment

This deploys Health Data Hub as a **parallel reference server** on `apps.internal` without touching the live HealthTrack/personal_stack runtime.

Defaults:

- Runtime host: `apps.internal`
- Remote code: `/srv/stacks/health-data-hub`
- Remote secrets/env: `/srv/localappdata/health-data-hub/.env`
- API: `http://apps.internal:18080`
- Grafana: `http://apps.internal:3300`
- Postgres/TimescaleDB: bound to `127.0.0.1:15432` on the VM only
- Home Assistant MQTT profile: **disabled by default**

Deploy from a clean repository:

```bash
./deploy/apps-vm/deploy.sh
```

Verify:

```bash
curl -fsS http://apps.internal:18080/health
curl -fsS http://apps.internal:18080/api/health
curl -fsS http://apps.internal:18080/ready
curl -fsS http://apps.internal:3300/api/health
ssh apps.internal 'cat /srv/localappdata/health-data-hub/current-release.env'
```

Important boundaries:

- Do not reuse HealthTrack's `/srv/stacks/healthtrack` or `/srv/localappdata/healthtrack` paths.
- Do not enable `homeassistant-mqtt` against the live Home Assistant broker until parity is reviewed; otherwise it may publish overlapping retained discovery/state topics.
- This is a reference/parallel activation lane, not a migration of the personal_stack runtime.
