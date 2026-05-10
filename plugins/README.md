# plugins/

Extensions discovered by filesystem walk + manifest. Every plugin
declares an `id`, `kind`, `version`, `sdk_version` (semver), runtime
entry, capabilities, and config schema. The SDK contract lives in
`packages/py/plugin_sdk/` and re-exports the manifest schema from
`packages/py/contracts/plugins.py` (a TS mirror at
`packages/ts/plugin-sdk/` is deferred until a TypeScript plugin
lands).

| dir | kind | what it produces |
|-----|------|------------------|
| `sources/` | `Source` | Normalized health measurements (Apple Health, Oura, Whoop, Garmin, manual logs) |
| `narrators/` | `Narrator` | LLM-rendered briefings from statistical findings (stateless) |
| `agents/` | `Agent` | Autonomous decisions + typed action proposals (stateful, daemonized) |

Built-in plugins live here in-tree. Third-party plugins will be
discovered out-of-process via the same manifest contract once the
sandbox lands (deferred to v2.1+).

## Discovery convention

```
plugins/
  sources/
    <plugin-id>/
      plugin.yaml        # PluginManifest (Pydantic-validated)
      __init__.py        # entrypoint module
      README.md          # author docs (recommended)
  narrators/<plugin-id>/...
  agents/<plugin-id>/...
  .generated/
    plugin-registry.json # build artifact, regenerated via the CLI below
```

The directory name is for the filesystem; the canonical id lives in
the manifest's `id` field. Hyphens are fine in the manifest id;
Python module dirs use underscores so the entrypoint resolves.
Example: `apple-health-healthsave` (id) →
`apple_health_healthsave/` (dir).

## Plugin manifest

`plugin.yaml` validates against
`packages/py/contracts/plugins.PluginManifest` (re-exported as
`plugin_sdk.PluginManifest`). Every field except defaults is
required. Unknown fields fail validation (V2Model `extra='forbid'`).

```yaml
id: my-plugin                      # canonical wire id
name: My Plugin                    # human-friendly name
kind: source                       # source | narrator | agent
version: "1.0.0"                   # plugin's own semver
sdk_version: ">=0.1,<0.2"          # SDK range this plugin targets
language: python                   # python | typescript
entrypoint: "plugins.sources.my_plugin:MyPluginClass"
config_schema: null                # optional path to a JSON schema
permissions:
  network: false
  secrets: []
  capabilities:
    - name: "write:measurements"
      description: "..."
emits: []                          # ['measurement.heart_rate', ...]
consumes: []                       # ['finding.anomaly', ...]
requires: []                       # other plugin ids this depends on
```

## sdk_version compatibility

The SDK ships a small semver matcher (`plugin_sdk.is_sdk_compatible`,
`assert_sdk_compatible`) that supports:

| form | meaning |
|------|---------|
| `*` | any (use sparingly) |
| `0.1.0` | exact |
| `>=0.1` | minimum |
| `>=0.1,<0.2` | range |
| `>0.1,<=0.2` | exclusive lower / inclusive upper |

Bump the SDK on every breaking contract change; bump it minor for
additive changes. The current SDK version is in
`packages/py/plugin_sdk/__about__.py` (`SDK_VERSION`).

## Generating the registry

```bash
PYTHONPATH=apps/api:apps/worker:packages/py \
  python -m plugin_sdk.registry
# wrote /…/plugins/.generated/plugin-registry.json
```

The registry is a build artifact — commit it so deploys don't need
to walk YAML at boot. CI can diff it to catch "you added a plugin
but forgot to commit the registry."

## Writing a new plugin

1. Pick a kind: `sources`, `narrators`, or `agents`.
2. Make a directory under that kind. Use underscores so the path
   imports cleanly (`my_new_plugin/`).
3. Write `plugin.yaml`. Use the example above as a template.
4. Write `__init__.py` that exports a class subclassing
   `plugin_sdk.Source` / `Narrator` / `Agent`. Implement the
   abstract methods (`Source.ingest`, `Narrator.render`,
   `Agent.observe` + `Agent.propose`).
5. Write a README explaining what the plugin does, what it emits /
   consumes, and any setup requirements.
6. Add a test in `tests/test_plugin_<id>.py` that mirrors the shape
   of `tests/test_plugin_apple_health.py`: manifest validates,
   entrypoint resolves to the right base class, plugin instantiates,
   `discover()` finds it.
7. Regenerate the registry (`python -m plugin_sdk.registry`) and
   commit the new file.

The first first-party Source plugin
(`plugins/sources/apple_health_healthsave/`) is the worked example.
