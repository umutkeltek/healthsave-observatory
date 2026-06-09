# Storage backends

The ingest path in HealthSave Observatory is pluggable. The default backend is TimescaleDB (a Postgres extension), which is what `setup.sh` provisions — but if you already run a different time-series store and don't want to add a second one, you can write a Python module that implements the `IngestStorage` protocol, register it, and point the server at it via environment variables.

The ingest API is intentionally simple so anyone can build a compatible backend. This page covers selecting a backend, writing your own, the community list, and how idempotent ingest works.

## Built-in backends

| Name | Backed by | Audit log | Notes |
|---|---|---|---|
| `postgres` (default) | TimescaleDB hypertables | yes (`raw_ingestion_log`) | Joins, transactions, continuous aggregates |

## Where the code lives

After the storage→API inversion, the storage layer is its own package and DB access lives **only** in `packages/py/storage/` (nothing else imports `sqlalchemy`):

- **Protocols** — `IngestStorage` and `AuditLog` are defined in `storage.ports` (`packages/py/storage/ports.py`).
- **Default Postgres implementation** — `PostgresIngestStorage` / `PostgresAuditLog` in `storage.timescale.ingest` (`packages/py/storage/timescale/ingest.py`).
- **Registry** — `register_backend`, `get_backend`, `load_plugins`, and `resolve_from_env` in `server.ingestion.registry` (`apps/api/server/ingestion/registry.py`).
- **Compatibility shim** — `server.ingestion.storage` re-exports `IngestStorage`, `AuditLog`, and the Postgres impls, so older imports against `server.ingestion.storage` keep working.

> Import the protocols from either `storage.ports` (canonical) or `server.ingestion.storage` (compatibility shim). The registry's `register_backend` is imported from `server.ingestion.registry`.

## Selecting a backend

```bash
HDH_STORAGE_BACKEND=postgres docker compose up -d   # explicit (also the default)
```

## Writing your own

For example, an InfluxDB, ClickHouse, DuckDB, or MQTT-only backend:

1. **Implement the storage protocol** — `IngestStorage` (`storage.ports.IngestStorage`) in your own package. It is two methods: `get_or_create_device()` and `ingest_metric()`.
2. **Optionally implement `AuditLog`** (`storage.ports.AuditLog`) if your store supports an audit-row pattern. Append-only stores (InfluxDB) can skip it; the route notices a `None` audit log and skips audit calls.
3. **Register a factory at module-import time** with `register_backend` from `server.ingestion.registry`:

   ```python
   # mycorp_health/influx_backend.py
   from server.ingestion.registry import register_backend

   def _influx_factory(config):
       from .influx_storage import InfluxIngestStorage
       return InfluxIngestStorage(config), None  # append-only, no AuditLog

   register_backend("influxdb", _influx_factory)
   ```

4. **Tell the server to load your plugin and use it:**

   ```bash
   HDH_STORAGE_PLUGINS=mycorp_health.influx_backend \
   HDH_STORAGE_BACKEND=influxdb \
   docker compose up -d
   ```

`HDH_STORAGE_PLUGINS` is comma-separated — multiple plugin modules are imported in order before the backend lookup runs. A failed plugin import is logged but does **not** abort startup, so a missing optional dependency degrades to "fall back to the built-in default" rather than "the server won't boot."

The protocols, the registry, the env resolver, and the worked Postgres example live in `packages/py/storage/ports.py`, `apps/api/server/ingestion/registry.py`, `packages/py/storage/timescale/ingest.py`, and the `server.ingestion.storage` shim.

## Community backends

The ingest API is simple enough that compatible backends already exist outside this repo:

- **[health-data-to-mqtt](https://github.com/bietiekay/health-data-to-mqtt)** by [@bietiekay](https://github.com/bietiekay) — a lightweight Node.js server that stores raw JSON and forwards selected metrics to MQTT. Built for alerting and home-automation pipelines where MQTT is the primary transport.

If you've built a compatible backend (a separate server speaking the [v1 ingest contract](../api/v1-apple-contract.md), or a Python `IngestStorage` plugin for this one), open an issue or PR and we'll list it here. The full wire contract is in [`API.md`](../../API.md); contribution flow is in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Deduplication: idempotent ingest

All ingestion is idempotent — you can safely re-sync or retry without inflating your data:

- Unique indexes on first-class metric identity columns.
- `INSERT ... ON CONFLICT DO UPDATE` for upsert behavior.
- In-memory dedup within each batch to avoid Postgres conflict errors on full-export overlap.

The API also stores each received batch in `raw_ingestion_log` before processing, then marks it processed after a successful commit. That gives you a minimal audit trail and a useful starting point for replay tooling. A custom backend should preserve the same idempotency guarantee (by batch ID, run ID, or a deterministic record key) so retries and backfills don't double-count.
