# deploy/

Deployment surfaces. Today: Docker Compose profiles + Grafana
provisioning. Future: optional cloud manifests (still optional —
local Compose is the canonical deploy).

| path | purpose | populated |
|------|---------|-----------|
| `grafana/` | Auto-provisioned Grafana datasource + dashboards (optional secondary surface) | Phase 1A |
| `compose/` | Per-service Compose profiles (`base`, `api`, `worker`, `web`, `local-llm`) | Phase 4 |
| `remote-vm/` | Optional SSH deploy helper for a generic Docker VM, including bundled or external Postgres/TimescaleDB modes | Reference |

The root `docker-compose.yml` stays the canonical zero-config
entrypoint at every phase boundary. Profile splits compose into it
without breaking `docker compose up -d`.
