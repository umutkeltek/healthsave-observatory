# plugins/

Extensions discovered by filesystem walk + manifest. Every plugin
declares an `id`, `kind`, `version`, `sdk_version` (semver), runtime
entry, capabilities, and config schema. The SDK contract lives in
`packages/py/plugin-sdk/` (and a TS mirror in `packages/ts/plugin-sdk/`).

| dir | kind | what it produces |
|-----|------|------------------|
| `sources/` | `Source` | Normalized health measurements (Apple Health, Oura, Whoop, Garmin, manual logs) |
| `narrators/` | `Narrator` | LLM-rendered briefings from statistical findings (stateless) |
| `agents/` | `Agent` | Autonomous decisions + typed action proposals (stateful, daemonized) |

Built-in plugins live here in-tree. Third-party plugins will be
discovered out-of-process via the same manifest contract once the
sandbox lands (deferred to v2.1+).
