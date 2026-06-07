# Source / Device / Stream separation — Implementation Plan (agent handoff)

**Status:** Plan only. NOT started. Do not push to remote until the owner says so.
**Design it implements:** [`contracts/SOURCE_DEVICE_MODEL.md`](./SOURCE_DEVICE_MODEL.md) — read it fully first; this plan assumes that vocabulary (Source / Device / Stream / exact_ingest_key / semantic_key / capability registry).
**Decision provenance:** Oracle GPT‑5.5 Pro, session `healthsave-source-device-separation-3` (transcript `~/.oracle/sessions/healthsave-source-device-separation-3/output.log`; reattach `oracle session healthsave-source-device-separation-3`).

---

## 0. Orientation — read these before touching code

- Design spec: `contracts/SOURCE_DEVICE_MODEL.md` (this plan's source of truth).
- Boundaries (machine-enforced; violating fails CI): `CLAUDE.md` + `AGENTS.md`. Summary: **DB access only in `packages/py/storage/`**; new client routes **only under `/api/v2/`**; `/api/apple/*` + `/api/insights/*` are FROZEN; adding a v2 route requires regenerating the OpenAPI lock (`make regen-lock` or `python -m scripts.generate_v1_lock`) and confirming a **v2-only** diff; two-brain (stats ⊥ LLM); raw rows never egress.
- Relevant memory (auto-memory dir): `project_datahub_source_device_stream_model`, `project_datahub_v2_architecture_decisions` (canonical-Observation spine this builds on), `project_personal_stack_retired_datahub_whoop` (Whoop is fully activated; deploy mechanics), `knowledge_ha_live_config_diverged_and_broke` (the live HA `_2`-entity tangle — see §6), `project_healthsave_homelab_topology` (infra).

## 1. Environment, build, test, deploy (so you can act immediately)

- Repo: `/Users/umut/Projects/products/healthsave/datahub`. Python 3.12. **Use the repo venv: `.venv/bin/python`** (the pyenv `python3.12` shim is not on PATH).
- Test: `.venv/bin/python -m pytest -q` (baseline **916 passed, 1 skipped** as of 2026-06-08). Per-file isolation matters — also run the specific new test files alone (see `feedback_test_isolation_per_file`).
- Lint: `.venv/bin/python -m ruff format --check .` + `.venv/bin/python -m ruff check .` (rules E,F,I,UP,B,SIM).
- OpenAPI lock (only if you add/modify a route): regen + confirm v2-only, no v1 drift. Phases 1/2/5/6 here are mostly storage + worker + bridge → usually **no** route change. Phase 4 adds `GET /api/v2/.../capabilities` (or `/api/apple/capabilities` — see §Phase 4) → lock regen required.
- **Migrations are MANUAL against the live DB** (`db.internal` = db-vm 192.168.33.213, native PostgreSQL+TimescaleDB 2.27, holds live data). Apply with:
  `ssh db.internal "sudo -n -u postgres psql -d healthsave -f -" < db/migrations/0NN_*.sql` (or paste the file). There is a compose `migrate` service, but the canonical live DB is external (db.internal) via the override — do not assume `up migrate` ran against it; verify with `\d <table>`.
- **Deploy a changed service (apps-vm `/srv/stacks/health-data-hub`, non-git, debian-owned):**
  1. `scp <changed source files> apps.internal:/srv/stacks/health-data-hub/<same relative path>`
  2. `ssh apps.internal "cd /srv/stacks/health-data-hub && sudo -n docker compose -f docker-compose.yml -f docker-compose.remote-vm.override.yml build <svc> && sudo -n docker compose -f docker-compose.yml -f docker-compose.remote-vm.override.yml up -d --no-deps <svc>"`
  - Services: `api`, `worker`, `homeassistant-mqtt` (the bridge, under `profiles: ["home-assistant"]` → add `--profile home-assistant` for it). The override maps `DATABASE_URL`→`${HEALTH_DATA_HUB_DB_HOST}`=db.internal; **plain `docker compose` (no `-f override`) points at the dead local `db`** — always include both `-f` files.
- **Commit discipline:** one logical change per commit, stage explicit paths (NOT `-A`), **redact-scan before any push** (`git diff … | redact`, exit 0), commit locally but **do not push** without the owner's OK (public repo).
- **COORDINATION — a parallel session is active in datahub** (security hardening: commits `SECURITY-001/006`, `CONTRACT-001`, plus uncommitted WIP touching `apps/api/server/api/ingest.py`, `v2_export.py`, `apps/api/server/main.py`, `tests/test_api_contract.py`, new `tests/test_request_limits.py`). **Check `git status` before editing those files; Phase 1's ingest dual-write touches `ingest.py` — coordinate or rebase.** datahub local `main` is ahead of `origin` with that session's work + the two design docs (`SOURCE_DEVICE_MODEL.md` `633b3d1`, this plan) — do not force-push.

## 2. What "done" looks like (acceptance for the whole effort)
- Every observation in `canonical_observations` carries `source_id`, `device_id` (nullable when unresolved), `stream_id`, `exact_ingest_key`, `semantic_key`, `is_primary`, `provenance`.
- HA publishes **one device per `source_device_stream`** with `unique_id` keyed on the stream UUID; the previously-orphaned `body_temperature` / `respiratory_rate` / per-source `apple_watch`/`iphone`/`whoop` data appears as clean per-stream entities.
- A capability registry (from `plugin.yaml` manifests) is the single source of truth for "which integration provides which data"; unknown plugin/metric emissions are quarantined.
- The v1 `/api/apple/batch` contract is unchanged; iOS additions are optional; old self-hosted backends keep working.

---

## 3. Phase 1 — datahub identity foundation  ← START HERE (safe-additive, no iOS release)

**Goal:** stand up the registry + resolver and dual-write canonical observations so EXISTING v1 rows resolve to stable canonical Source/Device/Stream. This alone delivers clean separation before any iOS change.

### 3.1 Migration `db/migrations/0NN_source_device_registry.sql` (additive)
Create the registry tables (DDL from the design spec §"Runtime registry tables"): `source_plugins`, `source_capabilities`, `source_instances`, `devices`, `source_device_streams`, `source_aliases` (UUID PKs, `owner_id`, hashed alias values, `identity_confidence`, `first/last_seen_at`; `source_aliases UNIQUE(owner_id, alias_kind, alias_value_hash)`). Copy the exact column lists from `SOURCE_DEVICE_MODEL.md`.

Extend `canonical_observations` (created in migration 012) — add: `stream_id uuid`, `exact_ingest_key uuid`, `semantic_key uuid`, `is_primary boolean not null default true`. Add `UNIQUE(owner_id, exact_ingest_key)` (partial/where-not-null if needed). Keep `source_id`/`device_id` already present.

Add nullable canonical columns to every v1 metric table (`heart_rate, hrv, blood_oxygen, body_temperature, workouts, daily_activity, sleep_sessions, quantity_samples` and the source-less ones `recovery, stress, sleep_stages`): `canonical_source_id uuid, canonical_device_id uuid, canonical_stream_id uuid, exact_ingest_key uuid, semantic_key uuid, provenance jsonb not null default '{}'`. Keep `source_id TEXT` and treat it as `raw_source_label`.

Idempotency: use `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`. **Do NOT drop/rename anything** (additive migrations rule).

### 3.2 Storage layer — `packages/py/storage/timescale/registry.py` (new; DB access lives here)
Implement the resolver + repos (all SQL here, not in routes/workers):
- `resolve_source_instance(session, *, owner_id, plugin_id, external_account_key=None) -> SourceInstance` — uuidv5(owner, plugin_id, account_key_hash); upsert into `source_instances`.
- `resolve_device(session, *, owner_id, provider_id, provider_device_id=None, fallback_account_id=None, hk_device=None) -> Device` — strong key = provider device id / HK UDI / HK local id (hashed); fallback fingerprint; sets `identity_confidence`.
- `resolve_stream(session, *, owner_id, source_id, device_id=None, origin_key) -> Stream` — persisted UUID, **created once, never recomputed after merge**.
- `resolve_from_legacy_label(session, *, owner_id, raw_source_label, plugin_id) -> (source_id, device_id|None, stream_id)` — uses `source_aliases` + the resolver priority (strong provider IDs → HK device ids → HK bundle+revision → HK bundle → alias table → legacy name). Records/updates alias rows.
- Key/hash helper: `hardware_id_hash = sha256(deployment_salt + raw)`; `short_base32(uuid)` for HA topic slugs.
- `exact_ingest_key(...)` and `semantic_key(...)` pure functions per the spec (mirror them; unit-test independently).
Add Protocols in `packages/py/storage/ports.py` + accessors in `packages/py/storage/defaults.py` (follow the existing `ExportRepository` pattern). Whitelist the new route-facing module in `tests/contract/test_storage_invariant.py` only if a route imports `AsyncSession` for typing (Phase 1 likely needs none).

### 3.3 Manifests
- New `plugins/sources/apple_health_healthsave/` already exists — add/extend its `plugin.yaml` to declare `id: apple-healthkit-ios`, `provider_id: apple_healthkit`, `gather_method: healthkit_read`, `injection_path: ios_push_api_apple_batch`, `identity.healthkit_source_key_priority`, and typed `emits:` (see spec example).
- Rename Whoop manifest: `id: whoop-oauth`, `aliases: [whoop-healthsave]`, `provider_id: whoop`, `gather_method: oauth_poll`, `injection_path: datahub_worker`, typed `emits:` (keep the old flat list working by normalizing at load). **Keep the old id resolvable via alias** (don't break the running worker which loads the manifest).
- Manifest loader (`plugin_sdk`): accept BOTH the old flat `emits: [measurement.x]` list and the new typed objects; normalize to the typed form at startup. Loader writes manifests into `source_plugins`/`source_capabilities` on boot.

### 3.4 Ingest dual-write — `apps/api/server/api/ingest.py`  ⚠ coordinate (other session edits this)
After the existing v1 write, also: resolve Source(`apple-healthkit-ios`,owner) → origin alias (from `source` string + future bundle id) → Device (if resolvable) → Stream; compute `exact_ingest_key`/`semantic_key`; write `canonical_observations` (+ stream_id, keys, is_primary, provenance) AND backfill the v1 row's new `canonical_*` columns. Reuse the existing canonical-observation writer (`normalize_apple_batch`) — it already sets `source_id`; extend it to also set stream/device/keys via the resolver. Make it a dual-write that NEVER fails the v1 ingest (canonical write errors get logged + the v1 path still 200s).

### 3.5 Tests
`tests/test_source_device_registry.py` (resolver: legacy-label resolution, alias upsert, stream-once-never-recomputed, device confidence, key functions), `tests/test_ingest_dual_write.py` (apple batch → canonical_observations populated with stream/keys; v1 row gets canonical columns; idempotent on re-ingest via exact_ingest_key). Keep the full suite green; mock the async session like `tests/test_homeassistant_mqtt_publish_loop.py`.

### 3.6 Deploy + verify
Apply the migration to db.internal (manual psql). Redeploy `api` + `worker` (override compose). Verify:
- `\d canonical_observations` shows the new columns; registry tables exist.
- After a live ingest cycle: `SELECT source_id, device_id, stream_id, count(*) FROM canonical_observations GROUP BY 1,2,3` shows resolved streams; the legacy `"Whoop"`/`"Apple Watch"`/`"Umut's Apple Watch"` labels each map to a stream via `source_aliases`.

**Phase 1 risks:** (a) the storage↔server circular import (`storage.timescale.measurements` ↔ `server.ingestion`) — import `server.db.session` before `storage` in any one-off script (see `project_personal_stack_retired_datahub_whoop`); (b) `ingest.py` edit collides with the parallel security session — rebase/coordinate; (c) `canonical_observations` may already have rows from migration 012 dual-write — make the column adds + backfill idempotent.

## 4. Phase 2 — canonical HA stream publishing (safe-additive)
- New `StreamHealthSnapshot` dataclass (replaces the role of `SourceHealthSnapshot`) in `packages/py/homeassistant_mqtt/`; `packages/py/storage/timescale/homeassistant.py` gains `fetch_snapshots_by_stream()` (query `canonical_observations`/v1 canonical columns grouped by `stream_id`).
- `bridge.py`: publish one HA device per stream; `unique_id = healthsave:stream:<stream_uuid>:<metric_id>`, state topic `<prefix>/stream/<stream_uuid>/state`, discovery `homeassistant/device/<prefix>_stream_<short>/config`; object_id `healthsave_<friendly_device_slug>_<stream_short>_<metric>`. **Deprecate `source_slug(raw_source_id)`** (keep it running one window for the existing slug entities).
- Per-source metric coverage becomes **registry-driven**: publish every capability with `ha.expose=true` + a projection + a fresh non-null value (HR, HRV, steps, calories, sleep dur/eff, blood_oxygen, **body_temperature, respiratory_rate**, recovery, strain, stress, sleep-stage minutes). Drop the hardcoded 4-metric `SOURCE_METRIC_SPECS`.
- Keep the legacy **aggregate parent** entities unchanged (don't break dashboards).
- Deploy the `homeassistant-mqtt` service (`--profile home-assistant`). Verify HA shows clean per-stream devices; confirm nothing existing goes `unavailable`.

## 5. Phase 3 — iOS v1.1 additive metadata (App Store release)
Repo `../ios_app`. Additive only to `/api/apple/batch` (HealthSync `SyncEngine` batch builder + `HealthKitExtractor`). Add batch fields (`client_schema_version`, `bridge_install_id` Keychain UUID, `captured_at`, `timezone`) + per-sample (`hk_uuid` from `HKObject.uuid`, `start_date/end_date`, `source_bundle_id` from `HKSource.bundleIdentifier`, `source_revision_*` from `HKSourceRevision`, `device_*` from `HKDevice`, `metadata_sync_*` from `HKMetadataKeySyncIdentifier/Version`, `aggregation_scope/method`). Minimum identity-critical set: `hk_uuid, source_bundle_id, source_revision_product_type, device_local_identifier|udi, metadata_sync_*`. **pbxproj has no synchronized groups — new files need 4 pbxproj entries** (`knowledge_ios_app_pbxproj_explicit_membership`). datahub resolver (Phase 1) consumes these to upgrade provisional streams to strong identities. Ship via TestFlight (build/sign: `.asc/`, `ExportOptions.plist`, `asc` CLI; current live = 1.5.4 build 48).

## 6. Phase 4 — source-scoped cumulative metrics (capability-gated)
- datahub: add `GET /api/apple/capabilities` (or a `/api/v2` equivalent — decide; if under `/api/v2` it needs an OpenAPI-lock regen) returning `{apple_batch_schema, accepts_source_metadata, accepts_source_scoped_statistics}`.
- iOS: when the backend advertises support, ALSO send per-source statistics rows (`HKStatisticsCollectionQuery` `separateBySource`) tagged `aggregation_scope:"source"` + `statistic_start/end`, while still sending the all-source row. datahub stores source-scoped rows as stream observations; **aggregate read still uses the all-source total** (never sum aggregate + components).

## 7. Phase 5 — direct-plugin canonicalization (safe-additive)
- Whoop + Amazfit workers call the registry resolver (`resolve_source_instance`/`resolve_device`/`resolve_stream`) before writing; write canonical ids + keep the literal `"Whoop"`/`"Amazfit"` as `raw_source_label` only.
- `recovery`, `stress`, `sleep_stages` writes set canonical source/stream (require for new writes; old rows → `legacy-unattributed` Source, excluded from per-stream HA).
- Runtime quarantine: reject observations from unknown `plugin_id` / unknown `metric_id` (against the registry).

## 8. Phase 6 — backfill + fusion views (safe-additive)
- Backfill: create canonical Sources (`apple-healthkit-ios`, `whoop-oauth`, `amazfit-oauth`, `legacy-unattributed`); create `source_aliases` from existing `source_id TEXT` values; backfill v1 canonical columns + `canonical_observations`; compute `exact_ingest_key`/`semantic_key` where derivable.
- Read models: `raw_stream_observations` (no dedup), `fused_device_observations` (dedup per device by semantic key), `fused_owner_observations` (owner aggregate, metric-specific fusion rules from the spec: freshest-primary for HR/HRV/SpO2/temp/resp; HealthKit all-source for steps/energy; one primary sleep session/night; provider-native recovery/strain stay provider-labeled).

## 9. Phase 7 — legacy cleanup (contract-affecting; LAST)
Stop publishing slug-based per-source HA entities (after a compatibility window); KEEP aggregate parent entities; KEEP `/api/apple/batch` + `source_id TEXT` (as raw_source_label) indefinitely; never require canonical UUIDs from iOS. This also subsumes the deferred legacy `healthtrack` MQTT-prefix unify (`MEMORY/FOLLOWUPS.md` item 1) — once streams are canonical, repoint the home-layer configs to canonical stream entities, then drop the `healthtrack` dual-publish env.

## 10. Safe vs breaking (gate every change against this)
Safe-additive (do freely): optional `/api/apple/batch` fields; registry tables; nullable canonical columns; dual-write; canonical HA stream entities. Breaking (do NOT, or gate): remove aggregate HA entities; rename/remove `source` in iOS payload; require iOS canonical UUIDs; send source-scoped step rows to old backends without the capability gate; rename a plugin id without an alias.

## 11. Open questions for the owner (resolve before/at Phase 1)
1. `deployment_salt` for hardware-id hashing — where stored (env? per-deploy secret)? Needed in Phase 1 §3.2.
2. Metric registry: is there a canonical metric_id ontology to validate `emits` against (`packages/py/contracts/ontology.py`?) or do we seed one? Capability validation (Phase 1/5) depends on it.
3. `/api/apple/capabilities` placement: under frozen `/api/apple/*` (additive GET, but that namespace is "frozen") vs a new `/api/v2/...`? Affects the iOS URL + OpenAPI lock (Phase 4).
4. Multi-tenant: tables carry `owner_id` — confirm the single-owner default UUID still applies for the self-host case (the Whoop token uses owner `…0001`).

---
**Handoff checklist for the next agent:** read `SOURCE_DEVICE_MODEL.md` → confirm parallel-session datahub state (`git status`, don't collide on `ingest.py`) → implement Phase 1 §3.1–3.6 → full suite + ruff green → manual migration on db.internal → deploy api+worker via override compose → verify canonical streams from existing v1 rows → STOP and report before Phase 2. Do not push to origin without the owner's OK.
