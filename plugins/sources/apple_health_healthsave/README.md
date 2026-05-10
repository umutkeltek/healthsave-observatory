# apple-health-healthsave — Apple Health (HealthSave bridge) Source plugin

First first-party Source plugin shipped with Phase 6 of datahub.
Wraps the existing `POST /api/apple/batch` ingest pipeline so the
HealthSave iOS app's wire contract stays unchanged while the system
gains a uniform plugin-model expression of "where does Apple Health
data enter."

## Status

| | |
|--|--|
| Plugin id | `apple-health-healthsave` |
| Kind | `source` |
| SDK target | `>=0.1,<0.2` |
| Plugin version | `1.0.0` |
| Loader-bound? | **No.** Phase 6 ships the manifest + module; the route still calls the ingest pipeline directly. Phase 7+ migrates the route to invoke the plugin via the loader. |
| Wire-contract impact | **None.** The plugin is a thin wrapper around the existing pipeline; behaviour is byte-identical to pre-Phase-6. |

## Why this plugin exists

Two reasons, both architectural:

1. **Uniformity.** Future Source plugins (Oura, Whoop, Garmin) ship in
   the same shape. The dashboard / runtime can list them all the same
   way; CI can validate them against the same `PluginManifest`
   schema; the same `discover()` walk finds them.
2. **Worked example.** Plugin authors get a real, in-tree, end-to-end
   example to read. The manifest covers every field they'll need;
   the wrapper module shows how to plug into existing storage
   helpers without reimplementing them.

This plugin does **NOT** duplicate ingest logic. The `AppleHealthSource`
class delegates to:

- `server.ingestion.parsers.group_samples_by_device` — split the
  batch by source device.
- `storage.timescale.measurements._get_or_create_device` — resolve
  or create the per-batch device row.
- `storage.timescale.measurements._ingest_metric` — dispatch the
  per-metric INSERT path (the same one the route uses).

Same observability counters fire (`INGEST_REJECTED`, `INGEST_ROWS`).
Same storage zone invariant holds. Same `WithOwnership` defaults
apply (sentinel UUID for single-user installs).

## Manifest

See `plugin.yaml` in this directory. Highlights:

- `entrypoint: plugins.sources.apple_health_healthsave:AppleHealthSource`
  — Python module path + class name.
- `emits` enumerates every measurement metric the wrapped ingest
  pipeline can produce. The dashboard can show this in a
  "supported metrics" UI; CI can cross-check that every metric
  corresponds to a route in `apps/api/server/api/ingest.py`.
- `permissions.network: false` — the plugin never reaches the
  internet; everything happens inside the API process.
- `permissions.capabilities` — declares the storage capabilities
  the plugin needs (`write:raw_ingestion_log`, `write:measurements`).
  Future loaders enforce these at runtime.

## Future work

Phase 7+:

- Route handler delegates to the plugin via the loader (loader
  resolves `entrypoint` → instantiates `AppleHealthSource(manifest)`
  → calls `await plugin.ingest({...})`).
- The legacy `_get_or_create_device` / `_ingest_metric` helpers can
  retire from `server.ingestion/` once every Source plugin has been
  migrated to call them via the storage zone Protocol.

## Testing

`tests/test_plugin_apple_health.py` covers:

- The manifest exists, parses, and validates against `PluginManifest`.
- The manifest's `entrypoint` resolves to a class that subclasses
  `plugin_sdk.Source`.
- The class can be instantiated with the manifest.
- `discover()` finds the plugin under the project's real `plugins/`
  directory.

The wrapper's `ingest()` method itself is integration-tested
implicitly via the existing `tests/test_api_contract.py` suite — that
test calls the route, the route calls into the same ingest pipeline,
the plugin (when wired in Phase 7+) will call the same pipeline.
Same coverage either way.
